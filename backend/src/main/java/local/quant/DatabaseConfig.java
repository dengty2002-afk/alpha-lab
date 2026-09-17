package local.quant;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.sqlite.SQLiteConfig;
import org.sqlite.SQLiteDataSource;
import javax.sql.DataSource;
import java.io.IOException;

@Configuration
public class DatabaseConfig {
    @Bean(destroyMethod="close") WorkspaceLease workspaceLease(PlatformPaths paths) throws IOException {return new WorkspaceLease(paths.workspace);}
    @Bean DataSource dataSource(PlatformPaths paths,WorkspaceLease lease) {
        SQLiteConfig config=new SQLiteConfig();
        config.setBusyTimeout(10_000);
        config.enforceForeignKeys(true);
        SQLiteDataSource source=new SQLiteDataSource(config);
        source.setUrl("jdbc:sqlite:"+paths.workspace.resolve("metadata.db"));
        return source;
    }
}
