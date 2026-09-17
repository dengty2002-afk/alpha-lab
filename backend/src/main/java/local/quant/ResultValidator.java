package local.quant;

import org.springframework.stereotype.Component;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;

@Component
public class ResultValidator {
    public record Validated(Map<String,Object> result,List<Map<String,Object>> artifacts) {}
    public Validated validate(Path run) throws IOException {
        Path resultFile=PlatformPaths.contained(run,"result.json");
        if(!Files.isRegularFile(resultFile) || Files.size(resultFile)>32*1024*1024) throw new IllegalArgumentException("Missing or oversized result.json");
        Map<String,Object> result=Json.read(resultFile);
        if(!"1.0".equals(result.get("schemaVersion")) || !"complete".equals(result.get("status"))) throw new IllegalArgumentException("Worker result has invalid schema or status");
        if(!(result.get("kind") instanceof String) || !(result.get("summary") instanceof Map) || !(result.get("charts") instanceof Map) || !(result.get("tables") instanceof Map) || !(result.get("provenance") instanceof Map) || !(result.get("warnings") instanceof List) || !(result.get("artifacts") instanceof List<?>)) throw new IllegalArgumentException("Worker result is missing required fields");
        Json.assertFinite(result);
        Set<String> names=new HashSet<>();
        List<Map<String,Object>> artifacts=new ArrayList<>();
        for(Object item:(List<?>)result.get("artifacts")) {
            Map<String,Object> artifact=Json.map(item);
            String name=Json.text(artifact,"name","");
            if(!name.matches("[\\p{L}\\p{N}_. -]{1,180}") || !names.add(name)) throw new IllegalArgumentException("Invalid or duplicate artifact name");
            String relative=Json.text(artifact,"path","");
            Path path=PlatformPaths.contained(run,relative);
            if(!Files.isRegularFile(path)) throw new IllegalArgumentException("Artifact is not a regular file: "+relative);
            artifacts.add(Map.of("name",name,"path",relative,"mimeType",Json.text(artifact,"mimeType","application/octet-stream"),"size",Files.size(path),"sha256",sha256(path)));
        }
        return new Validated(result,artifacts);
    }
    public static String sha256(Path path) throws IOException {
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(InputStream in=Files.newInputStream(path)) { byte[] buffer=new byte[65536];int count;while((count=in.read(buffer))!=-1) digest.update(buffer,0,count); }
            return HexFormat.of().formatHex(digest.digest());
        } catch(NoSuchAlgorithmException e) {throw new IllegalStateException(e);}
    }
}
