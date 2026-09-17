package local.quant;

import jakarta.annotation.PreDestroy;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

@Service
public class JobRunner {
    public static final Set<String> TYPES=Set.of("PROVIDER_PROBE","DATA_DOWNLOAD","DATA_IMPORT","GENERATE_FIXTURE","FACTOR_PREVIEW","FACTOR_ANALYSIS","MODEL_EXPERIMENT","EXPORT_REPORT");
    private final MetadataStore store;
    private final PlatformPaths paths;
    private final WorkerLauncher launcher;
    private final ResultValidator validator;
    private final EventHub hub;
    private final ExecutorService executor=Executors.newSingleThreadExecutor(Thread.ofPlatform().name("research-worker").factory());
    private final ExecutorService streams=Executors.newCachedThreadPool(Thread.ofVirtual().name("research-io-",0).factory());
    private final Map<String,Process> processes=new ConcurrentHashMap<>();
    private final AtomicBoolean busy=new AtomicBoolean();
    private volatile boolean stopping;
    public JobRunner(MetadataStore store,PlatformPaths paths,WorkerLauncher launcher,ResultValidator validator,EventHub hub) {
        this.store=store;this.paths=paths;this.launcher=launcher;this.validator=validator;this.hub=hub;
    }
    public Map<String,Object> submit(String type,Map<String,Object> config) throws IOException {
        if(!TYPES.contains(type)) throw new IllegalArgumentException("Unsupported job type: "+type);
        Json.assertFinite(config);
        if(Json.write(config).length()>1_000_000) throw new IllegalArgumentException("Job configuration is too large");
        Map<String,Object> frozen=new LinkedHashMap<>(config);
        if(type.equals("DATA_IMPORT")) {
            String path=Json.text(config,"path","");
            if(path.isBlank()) throw new IllegalArgumentException("DATA_IMPORT requires path");
            Path original=paths.permittedInput(path);
            String extension=original.getFileName().toString().toLowerCase(Locale.ROOT);
            if(!extension.endsWith(".csv") && !extension.endsWith(".parquet")) throw new IllegalArgumentException("DATA_IMPORT requires a CSV or Parquet file");
            extension=extension.endsWith(".csv")?".csv":".parquet";
            Path frozenFile=paths.workspace.resolve("uploads").resolve("frozen-"+UUID.randomUUID()+extension);
            Files.copy(original,frozenFile);
            frozen.put("path",frozenFile.toString());
            frozen.put("sourcePath",original.toString());
            frozen.put("sourceHash",ResultValidator.sha256(frozenFile));
        }
        if(frozen.containsKey("snapshotId") && !Json.text(frozen,"snapshotId","").matches("[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")) throw new IllegalArgumentException("Invalid snapshot identifier");
        if(frozen.containsKey("pluginSnapshot")) {
            Path pluginSnapshot=Path.of(Json.text(frozen,"pluginSnapshot","")).toAbsolutePath().normalize().toRealPath();
            if(!pluginSnapshot.startsWith(paths.workspace.toRealPath()) || !Files.isDirectory(pluginSnapshot)) throw new IllegalArgumentException("Plugin snapshot must be a directory inside workspace");
            frozen.put("pluginSnapshot",pluginSnapshot.toString());
        }
        if(type.equals("EXPORT_REPORT")) {
            String sourceId=Json.text(config,"sourceJobId",Json.text(config,"jobId",""));
            if(!sourceId.matches("[0-9a-fA-F-]{36}")) throw new IllegalArgumentException("EXPORT_REPORT requires a valid sourceJobId");
            if(!"SUCCEEDED".equals(store.job(sourceId).get("status"))) throw new IllegalArgumentException("Only successful jobs can be exported");
            if(!Json.write(store.result(sourceId)).equals(Json.write(Json.read(paths.run(sourceId).resolve("result.json"))))) throw new IllegalArgumentException("Source result changed since registration");
            frozen.put("sourceJobId",sourceId);
        }
        Map<String,Object> job=store.createJob(type,frozen);
        hub.publish((String)job.get("id"),Map.of("type","status","status","QUEUED","message","任务已进入持久队列"));
        return job;
    }
    public Map<String,Object> rerun(String id) throws IOException {
        Map<String,Object> previous=store.job(id);
        if(Set.of("QUEUED","RUNNING").contains(previous.get("status"))) throw new IllegalStateException("Wait for the active job to finish before rerunning");
        Map<String,Object> config=Json.map(previous.get("config"));
        Path frozenPlugins=paths.run(id).resolve("frozen_plugins");
        if(Files.isDirectory(frozenPlugins)) config.put("pluginSnapshot",frozenPlugins.toString());
        config.put("rerunOf",id);
        return submit((String)previous.get("type"),config);
    }
    @Scheduled(fixedDelay=500) public void poll() {
        if(stopping || !busy.compareAndSet(false,true)) return;
        try {
            Optional<Map<String,Object>> next=store.claimNext();
            if(next.isEmpty()) {busy.set(false);return;}
            executor.submit(()->{try {execute(next.get());} finally {busy.set(false);}});
        } catch(RuntimeException e) {busy.set(false);throw e;}
    }
    private void execute(Map<String,Object> job) {
        String id=(String)job.get("id");
        Process process=null;
        try {
            if(!"RUNNING".equals(store.job(id).get("status"))) return;
            Path run=paths.run(id);Files.createDirectories(run);
            Map<String,Object> document=new LinkedHashMap<>();
            document.put("schemaVersion","1.0");document.put("jobId",id);document.put("type",job.get("type"));document.put("config",job.get("config"));
            document.put("projectDir",paths.project.toString());document.put("workspaceDir",paths.workspace.toString());document.put("runDir",run.toString());
            Path jobFile=run.resolve("job.json");Files.writeString(jobFile,Json.write(document),StandardOpenOption.CREATE_NEW);
            hub.publish(id,Map.of("type","status","status","RUNNING","message","计算进程启动"));
            process=launcher.start(jobFile);processes.put(id,process);
            if(!"RUNNING".equals(store.job(id).get("status"))) {terminate(process);return;}
            Process active=process;
            Future<String> output=streams.submit(()->readStdout(id,active.getInputStream(),run.resolve("stdout.jsonl")));
            Future<?> errors=streams.submit(()->{readStderr(id,active.getErrorStream(),run.resolve("stderr.log"));return null;});
            if(!process.waitFor(paths.timeoutSeconds,TimeUnit.SECONDS)) {terminate(process);throw new IllegalStateException("Worker exceeded timeout of "+paths.timeoutSeconds+" seconds");}
            String protocolError=output.get(10,TimeUnit.SECONDS);
            errors.get(10,TimeUnit.SECONDS);
            if(!"RUNNING".equals(store.job(id).get("status"))) return;
            if(process.exitValue()!=0) throw new IllegalStateException("Worker exited with code "+process.exitValue()+(protocolError==null?"; see task diagnostic logs":": "+protocolError));
            if(protocolError!=null) throw new IllegalStateException(protocolError);
            ResultValidator.Validated validated=validator.validate(run);
            store.complete(id,validated.result(),validated.artifacts());
            hub.publish(id,Map.of("type","status","status","SUCCEEDED","progress",1,"message","运行完成，结果已校验并登记"));
        } catch(Exception e) {
            String status=(String)store.job(id).get("status");
            if(status.equals("RUNNING")) {
                String message=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();
                store.finish(id,"FAILED",message,null);
                hub.publish(id,Map.of("type","status","status","FAILED","message",message));
            }
        } finally {
            if(process!=null && process.isAlive()) terminate(process);
            processes.remove(id);
        }
    }
    private String readStdout(String id,InputStream input,Path log) throws IOException {
        long previous=-1;
        String protocolError=null;
        int count=0;
        try(BufferedReader reader=new BufferedReader(new InputStreamReader(input,StandardCharsets.UTF_8));BufferedWriter writer=Files.newBufferedWriter(log,StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW)) {
            String line;
            while((line=reader.readLine())!=null) {
                if(line.length()>1_000_000) {protocolError="Worker stdout event exceeds 1 MB";continue;}
                writer.write(line);writer.newLine();writer.flush();
                if(line.isBlank()) continue;
                try {
                    Map<String,Object> event=Json.object(line);
                    if(!"1.0".equals(event.get("schemaVersion")) || !(event.get("seq") instanceof Number number) || number.doubleValue()!=number.longValue() || number.longValue()<=previous) throw new IllegalArgumentException("Invalid schema or non-increasing integer event sequence");
                    previous=((Number)event.get("seq")).longValue();
                    String type=Json.text(event,"type","");
                    if(!Set.of("started","progress","log","artifact","result","error").contains(type)) throw new IllegalArgumentException("Unknown worker event type");
                    Json.assertFinite(event);
                    if(type.equals("progress") && event.get("progress") instanceof Number p) store.progress(id,p.doubleValue(),Json.text(event,"message","正在计算"));
                    if(type.equals("error")) protocolError=Json.text(event,"message","Worker reported an error");
                    if(count++<20000) hub.publish(id,event);
                } catch(IllegalArgumentException e) {
                    protocolError="Invalid worker JSONL protocol: "+e.getMessage();
                    if(count++<20000) hub.publish(id,Map.of("type","log","level","error","message",line.substring(0,Math.min(line.length(),2000))));
                }
            }
        }
        return protocolError;
    }
    private void readStderr(String id,InputStream input,Path log) throws IOException {
        int count=0;
        try(BufferedReader reader=new BufferedReader(new InputStreamReader(input,StandardCharsets.UTF_8));BufferedWriter writer=Files.newBufferedWriter(log,StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW)) {
            String line;
            while((line=reader.readLine())!=null) {
                writer.write(line);writer.newLine();writer.flush();
                if(count++<2000) hub.publish(id,Map.of("type","log","source","stderr","message",line.substring(0,Math.min(line.length(),8000))));
            }
        }
    }
    public Map<String,Object> cancel(String id) throws IOException {
        Map<String,Object> job=store.job(id);
        if(!Set.of("RUNNING","QUEUED").contains(job.get("status"))) return job;
        if(!store.finish(id,"CANCELLED",null,null)) return store.job(id);
        Process process=processes.get(id);
        // Snapshot before signalling: a cooperative launcher may immediately exit
        // and make its still-running Python children undiscoverable from the parent.
        List<ProcessHandle> descendants=process==null?List.of():process.descendants().toList();
        Path run=paths.run(id);
        if(Files.isDirectory(run)) Files.writeString(run.resolve("cancel.request"),MetadataStore.now());
        if(process!=null) streams.submit(()->cancelProcessTree(process,descendants));
        hub.publish(id,Map.of("type","status","status","CANCELLED","message","任务已取消"));
        return store.job(id);
    }
    private static void cancelProcessTree(Process process,List<ProcessHandle> captured) {
        Set<ProcessHandle> known=new LinkedHashSet<>(captured);
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
        try {
            while(System.nanoTime()<deadline) {
                known.addAll(snapshotTree(process,known));
                if(!process.isAlive() && known.stream().noneMatch(ProcessHandle::isAlive)) return;
                Thread.sleep(25);
            }
        } catch(InterruptedException e) {Thread.currentThread().interrupt();}
        finally {
            // Do this even if waitFor/the launcher would already report exit.
            terminate(process,known);
        }
    }
    private static List<ProcessHandle> snapshotTree(Process process,Collection<ProcessHandle> captured) {
        Set<ProcessHandle> all=new LinkedHashSet<>(captured);
        all.addAll(process.descendants().toList());
        // Retained children can outlive their launcher and create descendants.
        for(ProcessHandle child:List.copyOf(all)) all.addAll(child.descendants().toList());
        return List.copyOf(all);
    }
    private static void terminate(Process process) {
        terminate(process,List.of());
    }
    private static void terminate(Process process,Collection<ProcessHandle> captured) {
        // Materialize the whole tree before any destroy call changes ancestry.
        List<ProcessHandle> descendants=snapshotTree(process,captured);
        for(ProcessHandle child:descendants.reversed()) {
            try {if(child.isAlive()) child.destroyForcibly();}catch(RuntimeException ignored){}
        }
        if(process.isAlive()) process.destroyForcibly();
    }
    @PreDestroy public void shutdown() {
        stopping=true;
        processes.forEach((id,process)->{store.finish(id,"INTERRUPTED","Application shutdown interrupted worker",null);terminate(process);});
        executor.shutdownNow();streams.shutdownNow();
    }
}
