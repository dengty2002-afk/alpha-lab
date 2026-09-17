package local.quant;

import java.io.IOException;
import java.nio.file.Path;

@FunctionalInterface
public interface WorkerLauncher { Process start(Path jobFile) throws IOException; }
