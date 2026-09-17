package local.quant;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.nio.file.*;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class MetadataAndResultTest {
    @TempDir Path temporary;
    PlatformPaths paths;
    MetadataStore store;
    @BeforeEach void setup() throws Exception {
        paths=new PlatformPaths(temporary.toString(),temporary.resolve("workspace").toString(),"missing-python",30);
        var source=new DatabaseConfig().dataSource(paths,null);
        store=new MetadataStore(new JdbcTemplate(source),new DataSourceTransactionManager(source),paths);
        store.initialize();
    }
    @Test void versionCreationPreservesPreviousContent() {
        var original=store.createEntity("factors",Map.of("name","momentum","expression","$close"));
        var revised=new LinkedHashMap<>(original);revised.put("expression","Ref($close, 1)");
        var second=store.createEntity("factors",revised);
        assertEquals(2,second.get("version"));assertNotEquals(original.get("id"),second.get("id"));
        assertEquals("$close",store.entity("factors",(String)original.get("id")).orElseThrow().get("expression"));
        assertEquals(original.get("logicalId"),second.get("logicalId"));
    }
    @Test void restartInterruptsRunningJobAndPreservesQueuedJobs() throws Exception {
        var running=store.createJob("GENERATE_FIXTURE",Map.of());
        store.claimNext().orElseThrow();
        var queued=store.createJob("FACTOR_PREVIEW",Map.of());
        store.initialize();
        assertEquals("INTERRUPTED",store.job((String)running.get("id")).get("status"));
        assertEquals("QUEUED",store.job((String)queued.get("id")).get("status"));
        assertEquals(1,store.events((String)running.get("id"),0).size());
    }
    @Test void cancellationCannotBeOverwrittenByLateSuccess() {
        var job=store.createJob("GENERATE_FIXTURE",Map.of());String id=(String)job.get("id");store.claimNext();
        store.finish(id,"CANCELLED",null,null);
        assertThrows(IllegalStateException.class,()->store.complete(id,Map.of(),List.of()));
        assertEquals("CANCELLED",store.job(id).get("status"));
    }
    @Test void pathsRejectTraversalAbsoluteAndBackslashes() throws Exception {
        Path root=temporary.resolve("artifacts");Files.createDirectories(root);
        for(String path:List.of("../secrets.txt","../../secrets.txt","C:/Windows/test","x\\..\\secret")) assertThrows(IllegalArgumentException.class,()->PlatformPaths.contained(root,path));
        assertEquals(root.resolve("nested/plot.csv"),PlatformPaths.contained(root,"nested/plot.csv"));
    }
    @Test void resultRequiresContractAndContainedExistingArtifacts() throws Exception {
        Path run=paths.run("test-run");Files.createDirectories(run);
        Files.writeString(run.resolve("table.csv"),"x,y\n1,2\n");
        Map<String,Object> valid=result(List.of(Map.of("name","table.csv","path","table.csv","mimeType","text/csv")));
        Files.writeString(run.resolve("result.json"),Json.write(valid));
        var checked=new ResultValidator().validate(run);
        assertEquals(1,checked.artifacts().size());
        assertEquals(64,((String)checked.artifacts().getFirst().get("sha256")).length());
        valid.put("artifacts",List.of(Map.of("name","secret","path","../private.txt")));
        Files.writeString(run.resolve("result.json"),Json.write(valid));
        assertThrows(IllegalArgumentException.class,()->new ResultValidator().validate(run));
        valid.remove("artifacts");Files.writeString(run.resolve("result.json"),Json.write(valid));
        assertThrows(IllegalArgumentException.class,()->new ResultValidator().validate(run));
    }
    @Test void strictJsonRejectsDuplicateAndNonfiniteValues() {
        assertThrows(IllegalArgumentException.class,()->Json.object("{\"x\":1,\"x\":2}"));
        assertThrows(IllegalArgumentException.class,()->Json.object("{\"x\":NaN}"));
        assertThrows(IllegalArgumentException.class,()->Json.assertFinite(Map.of("x",Double.POSITIVE_INFINITY)));
    }
    @Test void unknownEntityRevisionIsRejected() {
        assertThrows(NoSuchElementException.class,()->store.createEntity("factors",Map.of("id","missing","name","bad revision")));
    }
    @Test void workspaceLeasePreventsConcurrentInstanceThenReleases() throws Exception {
        try(var lease=new WorkspaceLease(paths.workspace)) {
            assertThrows(java.nio.channels.OverlappingFileLockException.class,()->new WorkspaceLease(paths.workspace));
        }
        try(var next=new WorkspaceLease(paths.workspace)) {assertNotNull(next);}
    }
    @Test void modelResultApiAccessIsAuditedWithoutChangingImmutableResult() throws Exception {
        Map<String,Object> job=store.createJob("MODEL_EXPERIMENT",Map.of());
        String id=(String)job.get("id");store.claimNext();
        Map<String,Object> original=result(List.of());original.put("kind","MODEL_EXPERIMENT");
        Path run=paths.run(id);Files.createDirectories(run);
        Path file=run.resolve("result.json");Files.writeString(file,Json.write(original));
        String originalHash=ResultValidator.sha256(file);
        store.complete(id,original,List.of());
        assertEquals("NOT_VIEWED",store.job(id).get("testViewAuditStatus"));
        assertNull(store.job(id).get("testViewedAt"));
        store.result(id); // Internal validation/export lookup does not imply an external read.
        assertEquals(0L,store.job(id).get("testViewCount"));
        ApiController api=new ApiController(paths,new CatalogService(store,paths),store,null,null);
        assertEquals(original,api.result(id));
        var first=store.job(id);
        assertEquals("VIEWED",first.get("testViewAuditStatus"));assertEquals(1L,first.get("testViewCount"));
        assertNotNull(first.get("testViewedAt"));assertEquals(first.get("testViewedAt"),first.get("lastViewedAt"));
        Thread.sleep(2);
        api.result(id);
        var second=store.job(id);
        assertEquals(first.get("testViewedAt"),second.get("testViewedAt"));assertEquals(2L,second.get("testViewCount"));
        assertTrue(Instant.parse((String)second.get("lastViewedAt")).isAfter(Instant.parse((String)first.get("lastViewedAt"))));
        assertEquals(original,store.result(id));assertEquals(originalHash,ResultValidator.sha256(file));
        store.initialize();
        assertEquals(2L,store.job(id).get("testViewCount"));
        var bootstrap=new CatalogService(store,paths).bootstrap();
        assertEquals(second.get("testViewedAt"),Json.map(((List<?>)bootstrap.get("jobs")).getFirst()).get("testViewedAt"));
    }
    @Test void nonModelAndUnsuccessfulAccessDoNotCountAsTestExposure() {
        var job=store.createJob("GENERATE_FIXTURE",Map.of());String id=(String)job.get("id");store.claimNext();store.complete(id,result(List.of()),List.of());
        store.accessResult(id);
        assertEquals(0L,store.job(id).get("testViewCount"));assertEquals("NOT_APPLICABLE",store.job(id).get("testViewAuditStatus"));
        String failed=(String)store.createJob("MODEL_EXPERIMENT",Map.of()).get("id");store.finish(failed,"FAILED","test",null);
        assertThrows(IllegalStateException.class,()->store.accessResult(failed));assertEquals(0L,store.job(failed).get("testViewCount"));
    }
    @Test void migrationFromV1PreservesJobsAndMarksHistoricalAccessUnknown() throws Exception {
        var entity=store.createEntity("factors",Map.of("name","existing factor","expression","$close"));
        String id=(String)store.createJob("MODEL_EXPERIMENT",Map.of()).get("id");store.claimNext();store.complete(id,result(List.of()),List.of());
        var source=new DatabaseConfig().dataSource(paths,null);
        JdbcTemplate jdbc=new JdbcTemplate(source);
        jdbc.execute("DROP TABLE job_report_access");jdbc.update("DELETE FROM schema_migrations WHERE version=2");
        Set<Path> before;
        try(var files=Files.list(paths.workspace)) {before=new HashSet<>(files.toList());}
        Thread.sleep(2);
        store.initialize();
        assertEquals(2,jdbc.queryForObject("SELECT MAX(version) FROM schema_migrations",Integer.class));
        assertEquals("SUCCEEDED",store.job(id).get("status"));
        assertEquals(entity,store.entity("factors",(String)entity.get("id")).orElseThrow());
        assertEquals("UNTRACKED_HISTORY",store.job(id).get("testViewAuditStatus"));assertEquals(false,store.job(id).get("testViewHistoryKnown"));
        Path backup;
        try(var files=Files.list(paths.workspace)) {backup=files.filter(p->p.getFileName().toString().startsWith("metadata.pre-v2.")&&!before.contains(p)).findFirst().orElseThrow();}
        try(var connection=DriverManager.getConnection("jdbc:sqlite:"+backup);var query=connection.createStatement();var rows=query.executeQuery("SELECT MAX(version) FROM schema_migrations")) {
            assertTrue(rows.next());assertEquals(1,rows.getInt(1));
        }
        store.accessResult(id);assertEquals("VIEWED",store.job(id).get("testViewAuditStatus"));assertEquals(false,store.job(id).get("testViewHistoryKnown"));
    }
    static Map<String,Object> result(List<?> artifacts) {
        return new LinkedHashMap<>(Map.of("schemaVersion","1.0","kind","test","status","complete","summary",Map.of(),"charts",Map.of(),"tables",Map.of(),"warnings",List.of(),"artifacts",artifacts,"provenance",Map.of("synthetic",true)));
    }
}
