package local.quant;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import java.nio.file.Files;

@Configuration
public class WorkerConfig {
    @Bean WorkerLauncher workerLauncher(PlatformPaths paths) {
        return jobFile->{
            if(!Files.isRegularFile(paths.python)) throw new IllegalStateException("研究 Python 环境尚未准备好："+paths.python);
            ProcessBuilder builder=new ProcessBuilder(paths.python.toString(),"-m","quant_platform.worker","--job-file",jobFile.toString());
            builder.directory(paths.project.toFile());
            builder.environment().put("PYTHONPATH",paths.project.resolve("research/src").toString());
            builder.environment().put("PYTHONUNBUFFERED","1");
            builder.environment().put("PYTHONUTF8","1");
            builder.environment().put("PYTHONIOENCODING","utf-8");
            builder.environment().put("OMP_NUM_THREADS","4");
            builder.environment().put("OPENBLAS_NUM_THREADS","4");
            builder.environment().put("MKL_NUM_THREADS","4");
            return builder.start();
        };
    }
}
