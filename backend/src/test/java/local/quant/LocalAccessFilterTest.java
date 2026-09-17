package local.quant;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.*;
import static org.junit.jupiter.api.Assertions.*;

class LocalAccessFilterTest {
    private MockHttpServletResponse filter(String host,String remote,String origin,String type) throws Exception {
        var request=new MockHttpServletRequest("POST","/api/jobs");request.setServerName(host);request.setServerPort(8080);request.setRemoteAddr(remote);
        if(origin!=null) request.addHeader("Origin",origin);if(type!=null) request.setContentType(type);
        var response=new MockHttpServletResponse();new LocalAccessFilter().doFilter(request,response,new MockFilterChain());return response;
    }
    @Test void blocksCrossOriginAndDnsRebinding() throws Exception {
        assertEquals(403,filter("localhost","127.0.0.1","https://evil.example","application/json").getStatus());
        assertEquals(403,filter("evil.example","127.0.0.1",null,"application/json").getStatus());
        assertEquals(403,filter("localhost","192.168.1.4",null,"application/json").getStatus());
        assertEquals(403,filter("localhost","127.0.0.1",null,"text/plain").getStatus());
        assertEquals(403,filter("localhost","127.0.0.1","http://localhost:5173","application/json").getStatus());
    }
    @Test void allowsSameOriginAndLocalCli() throws Exception {
        assertEquals(200,filter("localhost","127.0.0.1","http://localhost:8080","application/json").getStatus());
        assertEquals(200,filter("127.0.0.1","127.0.0.1",null,"application/json").getStatus());
    }
}
