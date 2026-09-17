package local.quant;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;

@Component
public class EventHub {
    private final MetadataStore store;
    private final Map<String,CopyOnWriteArrayList<SseEmitter>> listeners=new ConcurrentHashMap<>();
    public EventHub(MetadataStore store) { this.store=store; }
    public synchronized void publish(String id,Map<String,Object> event) {
        Map<String,Object> saved=store.appendEvent(id,event);
        for(SseEmitter emitter:listeners.getOrDefault(id,new CopyOnWriteArrayList<>())) send(id,emitter,saved);
    }
    public synchronized SseEmitter subscribe(String id,long after) {
        store.job(id);
        SseEmitter emitter=new SseEmitter(0L);
        var clients=listeners.computeIfAbsent(id,k->new CopyOnWriteArrayList<>());
        clients.add(emitter);
        emitter.onCompletion(()->clients.remove(emitter));
        emitter.onTimeout(()->{clients.remove(emitter);emitter.complete();});
        emitter.onError(e->clients.remove(emitter));
        long cursor=after;
        while(true) {
            List<Map<String,Object>> page=store.events(id,cursor);
            for(Map<String,Object> event:page) send(id,emitter,event);
            if(page.size()<2000) break;
            cursor=((Number)page.getLast().get("eventId")).longValue();
        }
        try { emitter.send(SseEmitter.event().data(Json.write(Map.of("type","status","status",store.job(id).get("status"),"jobId",id)))); }
        catch(IOException e) {clients.remove(emitter);emitter.complete();}
        return emitter;
    }
    private void send(String id,SseEmitter emitter,Map<String,Object> event) {
        try { emitter.send(SseEmitter.event().id(String.valueOf(event.get("eventId"))).data(Json.write(event))); }
        catch(IOException | IllegalStateException e) {listeners.getOrDefault(id,new CopyOnWriteArrayList<>()).remove(emitter);emitter.complete();}
    }
    public synchronized void closeStreams() {
        listeners.values().forEach(clients->clients.forEach(SseEmitter::complete));
        listeners.clear();
    }
}
