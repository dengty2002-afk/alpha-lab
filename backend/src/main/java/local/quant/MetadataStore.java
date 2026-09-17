package local.quant;

import jakarta.annotation.PostConstruct;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.*;

@Repository
public class MetadataStore {
    private static final String JOB_SELECT="SELECT jobs.*,access.first_viewed_at,access.last_viewed_at,COALESCE(access.view_count,0) AS report_view_count,(SELECT applied_at FROM schema_migrations WHERE version=2) AS audit_started_at FROM jobs LEFT JOIN job_report_access access ON access.job_id=jobs.id";
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final PlatformPaths paths;
    public MetadataStore(JdbcTemplate jdbc,PlatformTransactionManager manager,PlatformPaths paths) {
        this.jdbc=jdbc; this.transaction=new TransactionTemplate(manager);this.paths=paths;
    }
    @PostConstruct public void initialize() throws IOException {
        jdbc.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)");
        Integer version=jdbc.queryForObject("SELECT COALESCE(MAX(version),0) FROM schema_migrations",Integer.class);
        if(version!=null && version>2) throw new IllegalStateException("Database schema is newer than this application");
        List<String> migrations=List.of("V1__initial.sql","V2__report_access.sql");
        for(int next=version+1;next<=migrations.size();next++) {
            // VACUUM INTO produces a consistent SQLite backup, including committed WAL data.
            Path backup=paths.workspace.resolve("metadata.pre-v"+next+"."+Instant.now().toEpochMilli()+"-"+UUID.randomUUID()+".db");
            jdbc.execute("VACUUM INTO '"+backup.toString().replace("'","''")+"'");
            String sql;
            try(var input=new ClassPathResource("db/"+migrations.get(next-1)).getInputStream()) {
                sql=new String(input.readAllBytes(),StandardCharsets.UTF_8);
            }
            final int migrationVersion=next;
            transaction.executeWithoutResult(tx->{for(String statement:sql.split(";")) if(!statement.isBlank()) jdbc.execute(statement);jdbc.update("INSERT INTO schema_migrations VALUES (?,?)",migrationVersion,now());});
        }
        jdbc.execute("PRAGMA journal_mode=WAL");
        for(Map<String,Object> job:jobsInState("RUNNING")) {
            String id=(String)job.get("id");
            finish(id,"INTERRUPTED","Application stopped before confirming worker completion",null);
            appendEvent(id,Map.of("type","status","status","INTERRUPTED","message","应用重启，未完成任务已标为中断"));
        }
    }
    public static String now() { return Instant.now().toString(); }
    public List<Map<String,Object>> entities(String kind) {
        return jdbc.query("SELECT data_json FROM entity_versions WHERE kind=? ORDER BY created_at DESC,version DESC",(rs,n)->Json.object(rs.getString(1)),kind);
    }
    public Optional<Map<String,Object>> entity(String kind,String id) {
        return jdbc.query("SELECT data_json FROM entity_versions WHERE kind=? AND id=?",(rs,n)->Json.object(rs.getString(1)),kind,id).stream().findFirst();
    }
    public synchronized Map<String,Object> createEntity(String kind,Map<String,Object> input) {
        String name=Json.text(input,"name","").trim();
        if(name.isBlank() || name.length()>200) throw new IllegalArgumentException("Name must contain 1–200 characters");
        Map<String,Object> record=new LinkedHashMap<>(input);
        String requested=Json.text(input,"id","");
        Map<String,Object> parent=requested.isBlank()?null:entity(kind,requested).orElse(null);
        if(!requested.isBlank() && parent==null) throw new NoSuchElementException("The entity version to revise does not exist");
        record.remove("parentId");
        String logical=parent==null?UUID.randomUUID().toString():Json.text(parent,"logicalId",requested);
        Integer previous=jdbc.queryForObject("SELECT COALESCE(MAX(version),0) FROM entity_versions WHERE kind=? AND logical_id=?",Integer.class,kind,logical);
        String id=UUID.randomUUID().toString();
        record.put("id",id);record.put("logicalId",logical);record.put("name",name);record.put("version",previous+1);record.put("createdAt",now());
        if(parent!=null) record.put("parentId",requested);
        jdbc.update("INSERT INTO entity_versions VALUES(?,?,?,?,?,?,?)",id,kind,logical,name,previous+1,Json.write(record),record.get("createdAt"));
        return record;
    }
    public synchronized void seed(String kind,Map<String,Object> input,String fallbackId) {
        String id=Json.text(input,"id",fallbackId);
        if(entity(kind,id).isPresent()) return;
        Map<String,Object> data=new LinkedHashMap<>(input);
        String name=Json.text(data,"name",id);
        data.put("id",id);data.put("logicalId",id);data.put("version",1);data.put("createdAt",now());
        jdbc.update("INSERT OR IGNORE INTO entity_versions VALUES(?,?,?,?,?,?,?)",id,kind,id,name,1,Json.write(data),data.get("createdAt"));
    }
    public Map<String,Object> createJob(String type,Map<String,Object> config) {
        String id=UUID.randomUUID().toString();
        jdbc.update("INSERT INTO jobs(id,type,status,config_json,created_at,message) VALUES(?,?,'QUEUED',?,?,?)",id,type,Json.write(config),now(),"等待运行");
        return job(id);
    }
    public Map<String,Object> job(String id) {
        return jdbc.query(JOB_SELECT+" WHERE jobs.id=?",this::readJob,id).stream().findFirst().orElseThrow(()->new NoSuchElementException("Job not found"));
    }
    public List<Map<String,Object>> jobs() { return jdbc.query(JOB_SELECT+" ORDER BY jobs.created_at DESC LIMIT 500",this::readJob); }
    public List<Map<String,Object>> jobsInState(String state) { return jdbc.query(JOB_SELECT+" WHERE jobs.status=? ORDER BY jobs.created_at,jobs.id",this::readJob,state); }
    private Map<String,Object> readJob(ResultSet rs,int n) throws SQLException {
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("id",rs.getString("id"));result.put("type",rs.getString("type"));result.put("status",rs.getString("status"));result.put("config",Json.object(rs.getString("config_json")));
        result.put("createdAt",rs.getString("created_at"));result.put("startedAt",rs.getString("started_at"));result.put("finishedAt",rs.getString("finished_at"));
        result.put("progress",rs.getDouble("progress"));result.put("message",rs.getString("message"));result.put("error",rs.getString("error"));
        result.put("hasResult",rs.getString("result_json")!=null);
        boolean model="MODEL_EXPERIMENT".equals(rs.getString("type"));
        long count=rs.getLong("report_view_count");
        boolean historyKnown=!Instant.parse(rs.getString("created_at")).isBefore(Instant.parse(rs.getString("audit_started_at")));
        result.put("testViewedAt",rs.getString("first_viewed_at"));
        result.put("lastViewedAt",rs.getString("last_viewed_at"));
        result.put("testViewCount",count);
        result.put("testViewHistoryKnown",historyKnown);
        result.put("testViewAuditStatus",!model?"NOT_APPLICABLE":count>0?"VIEWED":historyKnown?"NOT_VIEWED":"UNTRACKED_HISTORY");
        return result;
    }
    public synchronized Optional<Map<String,Object>> claimNext() {
        List<Map<String,Object>> queued=jobsInState("QUEUED");
        if(queued.isEmpty()) return Optional.empty();
        String id=(String)queued.getFirst().get("id");
        int updated=jdbc.update("UPDATE jobs SET status='RUNNING',started_at=?,message='正在运行' WHERE id=? AND status='QUEUED'",now(),id);
        return updated==1?Optional.of(job(id)):Optional.empty();
    }
    public void progress(String id,double progress,String message) {
        jdbc.update("UPDATE jobs SET progress=?,message=? WHERE id=? AND status='RUNNING'",Math.max(0,Math.min(1,progress)),message,id);
    }
    public synchronized boolean finish(String id,String status,String error,Map<String,Object> result) {
        return jdbc.update("UPDATE jobs SET status=?,finished_at=?,error=?,message=?,progress=CASE WHEN ?='SUCCEEDED' THEN 1 ELSE progress END,result_json=? WHERE id=? AND status IN ('QUEUED','RUNNING')",status,now(),error,status,status,result==null?null:Json.write(result),id)==1;
    }
    public synchronized void complete(String id,Map<String,Object> result,List<Map<String,Object>> artifacts) {
        transaction.executeWithoutResult(tx->{
            if(!"RUNNING".equals(job(id).get("status"))) throw new IllegalStateException("Job is no longer running");
            for(Map<String,Object> artifact:artifacts) jdbc.update("INSERT INTO artifacts VALUES(?,?,?,?,?,?)",id,artifact.get("name"),artifact.get("path"),artifact.get("mimeType"),artifact.get("size"),artifact.get("sha256"));
            Object resources=result.get("resources");
            if(resources instanceof List<?> list) for(Object resource:list) {
                Map<String,Object> value=Json.map(resource);
                if(!"snapshots".equals(value.get("kind"))) continue;
                jdbc.update("INSERT OR IGNORE INTO registered_resources VALUES(?,?,?,?)",value.get("kind"),value.get("id"),Json.write(value.get("data")),id);
            }
            finish(id,"SUCCEEDED",null,result);
        });
    }
    public Map<String,Object> result(String id) {
        job(id);
        String result=jdbc.queryForObject("SELECT result_json FROM jobs WHERE id=?",String.class,id);
        if(result==null) throw new IllegalStateException("No successful result is registered for this job");
        return Json.object(result);
    }
    /** External GET access is exposure even when the caller is an API tool or automatic fetch. */
    public synchronized Map<String,Object> accessResult(String id) {
        Map<String,Object> result=result(id);
        Map<String,Object> job=job(id);
        if("MODEL_EXPERIMENT".equals(job.get("type")) && "SUCCEEDED".equals(job.get("status"))) {
            String time=now();
            jdbc.update("INSERT INTO job_report_access(job_id,first_viewed_at,last_viewed_at,view_count) VALUES(?,?,?,1) ON CONFLICT(job_id) DO UPDATE SET last_viewed_at=excluded.last_viewed_at,view_count=job_report_access.view_count+1",id,time,time);
        }
        return result;
    }
    public Map<String,Object> artifact(String id,String name) {
        return jdbc.query("SELECT path,mime_type,size_bytes,sha256 FROM artifacts WHERE job_id=? AND name=?",(rs,n)->Map.<String,Object>of("path",rs.getString(1),"mimeType",rs.getString(2),"size",rs.getLong(3),"sha256",rs.getString(4)),id,name).stream().findFirst().orElseThrow(()->new NoSuchElementException("Artifact not registered"));
    }
    public synchronized Map<String,Object> appendEvent(String id,Map<String,Object> event) {
        Map<String,Object> copy=new LinkedHashMap<>(event);copy.put("jobId",id);copy.put("timestamp",now());
        jdbc.update("INSERT INTO job_events(job_id,event_json,created_at) VALUES(?,?,?)",id,Json.write(copy),copy.get("timestamp"));
        Long eventId=jdbc.queryForObject("SELECT MAX(id) FROM job_events WHERE job_id=?",Long.class,id);
        copy.put("eventId",eventId);return copy;
    }
    public List<Map<String,Object>> events(String id,long after) {
        return jdbc.query("SELECT id,event_json FROM job_events WHERE job_id=? AND id>? ORDER BY id LIMIT 2000",(rs,n)->{Map<String,Object> result=Json.object(rs.getString(2));result.put("eventId",rs.getLong(1));return result;},id,after);
    }
}
