package local.quant;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class JobRunnerTest {
    @TempDir Path temporary;
    MetadataStore store;JobRunner runner;PlatformPaths paths;
    void setup(String mode) throws Exception {
        String java=Path.of(System.getProperty("java.home"),"bin",System.getProperty("os.name").toLowerCase().contains("windows")?"java.exe":"java").toString();
        String classes=Path.of("target/test-classes").toAbsolutePath().toString();
        WorkerLauncher launcher=file->new ProcessBuilder(java,"-cp",classes,StubWorker.class.getName(),file.toString(),mode).start();
        setup(launcher);
    }
    void setup(WorkerLauncher launcher) throws Exception {
        paths=new PlatformPaths(temporary.toString(),temporary.resolve("workspace").toString(),"missing-python",30);
        var source=new DatabaseConfig().dataSource(paths,null);
        store=new MetadataStore(new JdbcTemplate(source),new DataSourceTransactionManager(source),paths);store.initialize();
        runner=new JobRunner(store,paths,launcher,new ResultValidator(),new EventHub(store));
    }
    @AfterEach void cleanup() {if(runner!=null) runner.shutdown();}
    @Test void successfulExitAndValidatedResultProduceSuccess() throws Exception {
        setup("success");String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        awaitTerminal(id);assertEquals("SUCCEEDED",store.job(id).get("status"));assertEquals("stub",store.result(id).get("kind"));
    }
    @Test void zeroExitWithoutResultIsFailure() throws Exception {
        setup("missing");String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        awaitTerminal(id);assertEquals("FAILED",store.job(id).get("status"));assertThrows(IllegalStateException.class,()->store.result(id));
    }
    @Test void nonzeroExitPersistsErrorAndDiagnostics() throws Exception {
        setup("exit");String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        awaitTerminal(id);assertEquals("FAILED",store.job(id).get("status"));assertTrue(store.events(id,0).stream().anyMatch(e->"stderr".equals(e.get("source"))));
    }
    @Test void cancelTerminatesActiveWorkerAndNeverRegistersResult() throws Exception {
        setup("wait");String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        long deadline=System.nanoTime()+10_000_000_000L;
        while(store.events(id,0).stream().noneMatch(e->"started".equals(e.get("type"))) && System.nanoTime()<deadline) Thread.sleep(25);
        assertTrue(store.events(id,0).stream().anyMatch(e->"started".equals(e.get("type"))));
        runner.cancel(id);assertEquals("CANCELLED",store.job(id).get("status"));assertThrows(IllegalStateException.class,()->store.result(id));
    }
    @Test void cancellationAllowsCooperativeWorkerToAcknowledgeBeforeForce() throws Exception {
        setup("cooperative");String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        awaitStarted(id);
        runner.cancel(id);
        awaitFile(paths.run(id).resolve("cooperative-exit"));
        assertEquals("CANCELLED",store.job(id).get("status"));
    }
    @Test void cancellationKillsCapturedChildAndGrandchildAfterLauncherExits() throws Exception {
        setup("tree-parent");String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        List<ProcessHandle> handles=new ArrayList<>();
        try {
            for(String name:List.of("tree-parent","tree-child","tree-grandchild")) {
                Path marker=paths.run(id).resolve(name+".pid");awaitFile(marker);
                ProcessHandle handle=ProcessHandle.of(Long.parseLong(Files.readString(marker))).orElseThrow();
                assertTrue(handle.isAlive());handles.add(handle);
            }
            runner.cancel(id);
            awaitFile(paths.run(id).resolve("launcher-exit"));
            awaitExited(handles);
            assertEquals("CANCELLED",store.job(id).get("status"));
            assertThrows(IllegalStateException.class,()->store.result(id));
        } finally {handles.reversed().forEach(p->{if(p.isAlive()) p.destroyForcibly();});}
    }
    @Test void cancellationCleansActualWindowsVenvLauncherAndInterpreter() throws Exception {
        Path python=Path.of("../research/.venv/Scripts/python.exe").toAbsolutePath().normalize();
        Assumptions.assumeTrue(System.getProperty("os.name").toLowerCase().contains("windows") && Files.isRegularFile(python),"Windows project Python integration environment");
        String script="import pathlib,os,sys,time; pathlib.Path(sys.argv[1], 'python-worker.pid').write_text(str(os.getpid())); time.sleep(30)";
        List<ProcessHandle> handles=new ArrayList<>();
        setup(file->{Process process=new ProcessBuilder(python.toString(),"-c",script,file.getParent().toString()).start();handles.add(process.toHandle());return process;});
        String id=(String)runner.submit("GENERATE_FIXTURE",Map.of()).get("id");runner.poll();
        try {
            Path marker=paths.run(id).resolve("python-worker.pid");awaitFile(marker);
            ProcessHandle interpreter=ProcessHandle.of(Long.parseLong(Files.readString(marker))).orElseThrow();
            handles.add(interpreter);
            assertNotEquals(handles.getFirst().pid(),interpreter.pid(),"This check must exercise a separate venv launcher");
            assertTrue(handles.stream().allMatch(ProcessHandle::isAlive));
            runner.cancel(id);
            awaitExited(handles);
            assertEquals("CANCELLED",store.job(id).get("status"));
        } finally {handles.reversed().forEach(p->{if(p.isAlive()) p.destroyForcibly();});}
    }
    @Test void importFreezesProjectInputBeforeEnteringQueue() throws Exception {
        setup("success");Path source=temporary.resolve("prices.csv");Files.writeString(source,"original data");
        var job=runner.submit("DATA_IMPORT",Map.of("path",source.toString()));
        Map<String,Object> config=Json.map(job.get("config"));
        Files.writeString(source,"changed data");
        Path frozen=Path.of((String)config.get("path"));
        assertTrue(frozen.startsWith(paths.workspace));assertEquals("original data",Files.readString(frozen));
        assertEquals(ResultValidator.sha256(frozen),config.get("sourceHash"));
    }
    @Test void exportsRejectFailedSourceAndSnapshotTraversal() throws Exception {
        setup("success");var source=store.createJob("GENERATE_FIXTURE",Map.of());
        store.finish((String)source.get("id"),"FAILED","test",null);
        assertThrows(IllegalArgumentException.class,()->runner.submit("EXPORT_REPORT",Map.of("sourceJobId",source.get("id"))));
        assertThrows(IllegalArgumentException.class,()->runner.submit("FACTOR_ANALYSIS",Map.of("snapshotId","..")));
    }
    @Test void rerunReferencesFrozenPluginsAndNewIdentity() throws Exception {
        setup("success");var source=store.createJob("FACTOR_ANALYSIS",Map.of("snapshotId","snap-test"));
        String id=(String)source.get("id");store.finish(id,"FAILED","test",null);
        Path plugins=paths.run(id).resolve("frozen_plugins");Files.createDirectories(plugins);
        var rerun=runner.rerun(id);var config=Json.map(rerun.get("config"));
        assertNotEquals(id,rerun.get("id"));assertEquals(id,config.get("rerunOf"));
        assertEquals(plugins.toString(),config.get("pluginSnapshot"));
        assertThrows(IllegalArgumentException.class,()->runner.submit("FACTOR_ANALYSIS",Map.of("pluginSnapshot",temporary.toString())));
    }
    private void awaitTerminal(String id) throws Exception {
        long deadline=System.nanoTime()+10_000_000_000L;
        while(Set.of("QUEUED","RUNNING").contains(store.job(id).get("status")) && System.nanoTime()<deadline) Thread.sleep(25);
        assertFalse(Set.of("QUEUED","RUNNING").contains(store.job(id).get("status")),"Worker did not terminate");
    }
    private void awaitStarted(String id) throws Exception {
        long deadline=System.nanoTime()+10_000_000_000L;
        while(store.events(id,0).stream().noneMatch(e->"started".equals(e.get("type"))) && System.nanoTime()<deadline) Thread.sleep(25);
        assertTrue(store.events(id,0).stream().anyMatch(e->"started".equals(e.get("type"))));
    }
    private void awaitFile(Path path) throws Exception {
        long deadline=System.nanoTime()+10_000_000_000L;
        while((!Files.isRegularFile(path) || Files.size(path)==0) && System.nanoTime()<deadline) Thread.sleep(25);
        assertTrue(Files.isRegularFile(path) && Files.size(path)>0,"Missing process marker: "+path);
    }
    private void awaitExited(List<ProcessHandle> handles) throws Exception {
        long deadline=System.nanoTime()+10_000_000_000L;
        while(handles.stream().anyMatch(ProcessHandle::isAlive) && System.nanoTime()<deadline) Thread.sleep(25);
        assertTrue(handles.stream().noneMatch(ProcessHandle::isAlive),"Task process survived cancellation: "+handles);
    }
}
