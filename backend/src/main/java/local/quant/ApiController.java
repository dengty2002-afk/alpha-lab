package local.quant;

import org.springframework.core.io.FileSystemResource;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

@RestController
@RequestMapping("/api")
public class ApiController {
    private final PlatformPaths paths;
    private final CatalogService catalog;
    private final MetadataStore store;
    private final JobRunner runner;
    private final EventHub hub;
    public ApiController(PlatformPaths paths,CatalogService catalog,MetadataStore store,JobRunner runner,EventHub hub) {
        this.paths=paths;this.catalog=catalog;this.store=store;this.runner=runner;this.hub=hub;
    }
    @GetMapping("/health") public Map<String,Object> health() {
        return Map.of("status","ok","pythonReady",Files.isRegularFile(paths.python),"workspace",paths.workspace.toString(),"javaVersion",System.getProperty("java.version"),"schemaVersion","1.0");
    }
    @GetMapping("/bootstrap") public Map<String,Object> bootstrap() throws IOException {return catalog.bootstrap();}
    @GetMapping("/entities/{kind}") public List<Map<String,Object>> entities(@PathVariable String kind) {catalog.validateKind(kind);return store.entities(kind);}
    @GetMapping("/entities/{kind}/{id}") public Map<String,Object> entity(@PathVariable String kind,@PathVariable String id) {catalog.validateKind(kind);return store.entity(kind,id).orElseThrow(()->new NoSuchElementException("Entity not found"));}
    @PostMapping("/entities/{kind}") @ResponseStatus(HttpStatus.CREATED)
    public Map<String,Object> createEntity(@PathVariable String kind,@RequestBody Map<String,Object> record) {
        catalog.validateKind(kind);Json.assertFinite(record);
        if(Json.write(record).length()>1_000_000) throw new IllegalArgumentException("Entity is too large");
        return store.createEntity(kind,record);
    }
    @GetMapping("/data/snapshots") public List<Map<String,Object>> snapshots() throws IOException {return catalog.snapshots();}
    @GetMapping("/operators") public List<Map<String,Object>> operators() throws IOException {return catalog.operators();}
    @PostMapping(value="/uploads",consumes=MediaType.MULTIPART_FORM_DATA_VALUE) @ResponseStatus(HttpStatus.CREATED)
    public Map<String,Object> upload(@RequestParam("file") MultipartFile file) throws IOException {
        if(file.isEmpty()) throw new IllegalArgumentException("Upload is empty");
        String original=Optional.ofNullable(file.getOriginalFilename()).orElse("upload.csv");
        original=original.replace('\\','/');original=original.substring(original.lastIndexOf('/')+1);
        String lower=original.toLowerCase(Locale.ROOT);
        if(!List.of(".csv",".parquet",".json",".txt").stream().anyMatch(lower::endsWith)) throw new IllegalArgumentException("Only CSV, Parquet, JSON and text uploads are supported");
        String safe=original.replaceAll("[^\\p{L}\\p{N}_. -]","_");
        if(safe.length()>180) safe=safe.substring(safe.length()-180);
        Path destination=PlatformPaths.contained(paths.workspace.resolve("uploads"),UUID.randomUUID()+"-"+safe);
        try(var input=file.getInputStream()) {Files.copy(input,destination);}
        return Map.of("path",destination.toString(),"name",original,"size",Files.size(destination),"sha256",ResultValidator.sha256(destination));
    }
    @GetMapping("/jobs") public List<Map<String,Object>> jobs() {return store.jobs();}
    @PostMapping("/jobs") @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String,Object> createJob(@RequestBody Map<String,Object> request) throws IOException {
        return runner.submit(Json.text(request,"type",""),request.get("config")==null?Map.of():Json.map(request.get("config")));
    }
    @GetMapping("/jobs/{id}") public Map<String,Object> job(@PathVariable String id) {return store.job(id);}
    @PostMapping("/jobs/{id}/cancel") public Map<String,Object> cancel(@PathVariable String id) throws IOException {return runner.cancel(id);}
    @PostMapping("/jobs/{id}/rerun") @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String,Object> rerun(@PathVariable String id) throws IOException {return runner.rerun(id);}
    @GetMapping(value="/jobs/{id}/events",produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@PathVariable String id,@RequestHeader(value="Last-Event-ID",required=false) String lastEventId,@RequestParam(defaultValue="0") long after) {
        if(lastEventId!=null) try {after=Long.parseLong(lastEventId);}catch(NumberFormatException e){throw new IllegalArgumentException("Invalid Last-Event-ID");}
        return hub.subscribe(id,Math.max(0,after));
    }
    @GetMapping("/jobs/{id}/logs") public List<Map<String,Object>> logs(@PathVariable String id,@RequestParam(defaultValue="0") long after) {store.job(id);return store.events(id,after);}
    @GetMapping("/jobs/{id}/result") public Map<String,Object> result(@PathVariable String id) {return store.accessResult(id);}
    @GetMapping("/jobs/{id}/artifacts/{name}") public ResponseEntity<FileSystemResource> artifact(@PathVariable String id,@PathVariable String name) throws IOException {
        Map<String,Object> artifact=store.artifact(id,name);
        Path file=PlatformPaths.contained(paths.run(id),(String)artifact.get("path"));
        if(!Files.isRegularFile(file)) throw new NoSuchElementException("Artifact file is missing");
        if(Files.size(file)!=((Number)artifact.get("size")).longValue() || !ResultValidator.sha256(file).equals(artifact.get("sha256"))) throw new IllegalStateException("Artifact changed since registration");
        MediaType contentType;
        try {contentType=MediaType.parseMediaType((String)artifact.get("mimeType"));}catch(Exception e){contentType=MediaType.APPLICATION_OCTET_STREAM;}
        return ResponseEntity.ok().contentType(contentType).contentLength(Files.size(file))
            .header(HttpHeaders.CONTENT_DISPOSITION,ContentDisposition.attachment().filename(name,java.nio.charset.StandardCharsets.UTF_8).build().toString())
            .header("Content-Security-Policy","sandbox")
            .body(new FileSystemResource(file));
    }
}
