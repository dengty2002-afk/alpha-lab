package local.quant;

import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
public class ShutdownController {
    private final ConfigurableApplicationContext context;
    private final EventHub hub;
    private final JobRunner runner;
    public ShutdownController(ConfigurableApplicationContext context,EventHub hub,JobRunner runner) {this.context=context;this.hub=hub;this.runner=runner;}
    @PostMapping("/api/shutdown") @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String,Object> shutdown() {
        Thread.ofPlatform().name("platform-shutdown").start(()->{
            try {Thread.sleep(250);}catch(InterruptedException e){Thread.currentThread().interrupt();}
            hub.closeStreams();
            runner.shutdown();
            context.close();
        });
        return Map.of("status","shutting_down");
    }
}
