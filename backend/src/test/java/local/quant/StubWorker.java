package local.quant;

import java.nio.file.*;
import java.util.*;

/** Deliberately isolated test executable; never reachable from production configuration. */
public class StubWorker {
    public static void main(String[] args) throws Exception {
        Path run=Path.of(args[0]).getParent();String mode=args[1];
        System.out.println("{\"schemaVersion\":\"1.0\",\"seq\":1,\"type\":\"started\"}");
        System.out.flush();
        if(mode.equals("cooperative")) {
            while(!Files.exists(run.resolve("cancel.request"))) Thread.sleep(10);
            Thread.sleep(150);
            Files.writeString(run.resolve("cooperative-exit"),"acknowledged cancel.request");
            return;
        }
        if(mode.startsWith("tree-")) {
            Files.writeString(run.resolve(mode+".pid"),Long.toString(ProcessHandle.current().pid()));
            if(!mode.equals("tree-grandchild")) {
                String java=Path.of(System.getProperty("java.home"),"bin",System.getProperty("os.name").toLowerCase().contains("windows")?"java.exe":"java").toString();
                String next=mode.equals("tree-parent")?"tree-child":"tree-grandchild";
                new ProcessBuilder(java,"-cp",System.getProperty("java.class.path"),StubWorker.class.getName(),args[0],next)
                    .redirectOutput(ProcessBuilder.Redirect.DISCARD).redirectError(ProcessBuilder.Redirect.DISCARD).start();
            }
            if(mode.equals("tree-parent")) {
                while(!Files.exists(run.resolve("cancel.request"))) Thread.sleep(10);
                Files.writeString(run.resolve("launcher-exit"),"launcher exits without waiting for children");
                return;
            }
            Thread.sleep(30_000);
            return;
        }
        if(mode.equals("wait")) {Thread.sleep(30_000);return;}
        if(mode.equals("exit")) {System.err.println("intentional failure");System.exit(2);}
        if(mode.equals("missing")) return;
        Files.writeString(run.resolve("result.json"),"{\"schemaVersion\":\"1.0\",\"kind\":\"stub\",\"status\":\"complete\",\"summary\":{},\"charts\":{},\"tables\":{},\"warnings\":[],\"artifacts\":[],\"provenance\":{\"testOnly\":true}}");
        System.out.println("{\"schemaVersion\":\"1.0\",\"seq\":2,\"type\":\"result\",\"path\":\"result.json\"}");
    }
}
