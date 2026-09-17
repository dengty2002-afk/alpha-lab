package local.quant;

import java.io.IOException;
import java.nio.channels.*;
import java.nio.file.*;

/** Held for this JVM's lifetime, so restart recovery cannot interrupt a second live app. */
public final class WorkspaceLease implements AutoCloseable {
    private final FileChannel channel;
    private final FileLock lock;
    public WorkspaceLease(Path workspace) throws IOException {
        channel=FileChannel.open(workspace.resolve(".platform.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);
        try {
            lock=channel.tryLock();
            if(lock==null) throw new IllegalStateException("Another platform instance is using workspace: "+workspace);
        } catch(IOException | RuntimeException e) {channel.close();throw e;}
    }
    @Override public void close() throws IOException {
        if(lock.isValid()) lock.release();
        channel.close();
    }
}
