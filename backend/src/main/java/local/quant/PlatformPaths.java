package local.quant;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.nio.file.*;

@Component
public class PlatformPaths {
    public final Path project;
    public final Path workspace;
    public final Path python;
    public final long timeoutSeconds;
    public PlatformPaths(@Value("${quant.project-dir:}") String projectDir,
                         @Value("${quant.workspace-dir:}") String workspaceDir,
                         @Value("${quant.worker-python:}") String workerPython,
                         @Value("${quant.worker-timeout-seconds:3600}") long timeoutSeconds) throws IOException {
        Path current=Path.of("").toAbsolutePath().normalize();
        if(projectDir.isBlank()) project = (Files.isDirectory(current.resolve("contracts")) ? current : current.getParent()).toRealPath();
        else project=Path.of(projectDir).toAbsolutePath().normalize().toRealPath();
        workspace=(workspaceDir.isBlank()?project.resolve("workspace"):Path.of(workspaceDir)).toAbsolutePath().normalize();
        Files.createDirectories(workspace);
        Files.createDirectories(workspace.resolve("runs"));
        Files.createDirectories(workspace.resolve("uploads"));
        Files.createDirectories(workspace.resolve("snapshots"));
        python=(workerPython.isBlank()?project.resolve("research/.venv/Scripts/python.exe"):Path.of(workerPython)).toAbsolutePath().normalize();
        this.timeoutSeconds=Math.max(10,timeoutSeconds);
    }
    public Path run(String id) { return contained(workspace.resolve("runs"), id); }
    public static Path contained(Path root,String relative) {
        Path requested=Path.of(relative);
        if(requested.isAbsolute() || relative.contains(":") || relative.contains("\\") || relative.isBlank()) throw new IllegalArgumentException("Invalid relative artifact path");
        Path resolved=root.resolve(requested).toAbsolutePath().normalize();
        if(!resolved.startsWith(root.toAbsolutePath().normalize()) || resolved.equals(root.toAbsolutePath().normalize())) throw new IllegalArgumentException("Path escapes allowed directory");
        try {
            Path existing=resolved;
            while(existing!=null && !Files.exists(existing,LinkOption.NOFOLLOW_LINKS)) existing=existing.getParent();
            if(existing!=null && !existing.toRealPath().startsWith(root.toRealPath())) throw new IllegalArgumentException("Symbolic link escapes allowed directory");
        } catch(IOException e) { throw new IllegalArgumentException("Cannot validate path",e); }
        return resolved;
    }
    public Path permittedInput(String value) throws IOException {
        Path candidate=Path.of(value);
        if(!candidate.isAbsolute()) candidate=project.resolve(candidate);
        candidate=candidate.toRealPath();
        if(!candidate.startsWith(project) && !candidate.startsWith(workspace.toRealPath())) throw new IllegalArgumentException("Input file must be within project or workspace");
        if(!Files.isRegularFile(candidate)) throw new IllegalArgumentException("Input must be a regular file");
        return candidate;
    }
}
