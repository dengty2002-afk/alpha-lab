package local.quant;

import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Service;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

@Service
public class CatalogService {
    public static final Set<String> KINDS=Set.of("factors","universes","experiments");
    private final MetadataStore store;
    private final PlatformPaths paths;
    public CatalogService(MetadataStore store,PlatformPaths paths) {this.store=store;this.paths=paths;}
    @PostConstruct public void seedDefaults() throws IOException {
        seed("factors","factors.json");seed("universes","universe.json");seed("experiments","experiments.json");
    }
    private void seed(String kind,String name) throws IOException {
        Path file=paths.project.resolve("examples").resolve(name);
        if(Files.isRegularFile(file)) {
            int index=0;
            for(Map<String,Object> entity:Json.array(file)) store.seed(kind,entity,"example-"+kind+"-"+(++index));
        }
    }
    public List<Map<String,Object>> snapshots() throws IOException {
        List<Map<String,Object>> result=new ArrayList<>();
        try(DirectoryStream<Path> directories=Files.newDirectoryStream(paths.workspace.resolve("snapshots"))) {
            for(Path directory:directories) {
                if(!Files.isDirectory(directory,LinkOption.NOFOLLOW_LINKS)) continue;
                Path manifest=PlatformPaths.contained(directory,"manifest.json");
                if(!Files.isRegularFile(manifest) || Files.size(manifest)>4*1024*1024) continue;
                try {
                    Map<String,Object> entry=Json.read(manifest);
                    if(!directory.getFileName().toString().equals(entry.get("id"))) continue;
                    entry.put("manifestPath",manifest.toString());result.add(entry);
                } catch(IllegalArgumentException e) {
                    result.add(Map.of("id",directory.getFileName().toString(),"name",directory.getFileName().toString(),"valid",false,"error","无效快照清单："+e.getMessage()));
                }
            }
        }
        result.sort(Comparator.comparing(m->String.valueOf(m.get("id"))));return result;
    }
    public List<Map<String,Object>> operators() throws IOException {
        for(Path source:List.of(paths.project.resolve("research/operator-catalog.json"),paths.project.resolve("examples/operators.json"))) {
            if(Files.isRegularFile(source)) return Json.array(source);
        }
        return List.of();
    }
    public Map<String,Object> bootstrap() throws IOException {
        Map<String,Object> bootstrap=new LinkedHashMap<>();
        bootstrap.put("factors",store.entities("factors"));bootstrap.put("universes",store.entities("universes"));bootstrap.put("experiments",store.entities("experiments"));
        bootstrap.put("snapshots",snapshots());bootstrap.put("jobs",store.jobs());bootstrap.put("operators",operators());
        bootstrap.put("defaults",Map.of("startDate","2021-01-01","endDate","2025-12-31","horizons",List.of(1,5,10,20),"costBps",List.of(0,5,10,20),"rebalancePeriods",List.of(1,5),"minUniverse",20,"models",List.of("equal_weight","ridge","lightgbm"),"seed",20260917,"pythonReady",Files.isRegularFile(paths.python)));
        return bootstrap;
    }
    public void validateKind(String kind) {if(!KINDS.contains(kind)) throw new IllegalArgumentException("Unknown entity kind");}
}
