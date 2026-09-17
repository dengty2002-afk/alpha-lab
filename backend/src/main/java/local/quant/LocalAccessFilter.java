package local.quant;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.net.URI;
import java.util.*;

/** Loopback only; rejects hostile Host/Origin headers and browser cross-site requests. */
@Component
public class LocalAccessFilter extends OncePerRequestFilter {
    private static final Set<String> LOOPBACK=Set.of("127.0.0.1","localhost","::1","0:0:0:0:0:0:0:1","[::1]");
    @Override protected boolean shouldNotFilterAsyncDispatch() {return true;}
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
        String host=request.getServerName().toLowerCase(Locale.ROOT);
        if(!LOOPBACK.contains(request.getRemoteAddr()) || !LOOPBACK.contains(host)) {reject(response,"仅允许本机回环地址访问");return;}
        String origin=request.getHeader("Origin");
        if(origin!=null) {
            try {
                URI parsed=URI.create(origin);
                int port=parsed.getPort()<0?("https".equals(parsed.getScheme())?443:80):parsed.getPort();
                if(!Objects.equals(parsed.getHost(),request.getServerName()) || port!=request.getServerPort() || !Objects.equals(parsed.getScheme(),request.getScheme()) || parsed.getUserInfo()!=null || parsed.getRawQuery()!=null || (parsed.getRawPath()!=null && !parsed.getRawPath().isBlank())) {reject(response,"跨站请求已拒绝；请使用应用的本机入口");return;}
            } catch(IllegalArgumentException e) {reject(response,"无效 Origin");return;}
        }
        String fetchSite=request.getHeader("Sec-Fetch-Site");
        if("cross-site".equals(fetchSite) || "same-site".equals(fetchSite)) {reject(response,"仅允许同源浏览器请求");return;}
        if(request.getRequestURI().startsWith("/api") && !Set.of("GET","HEAD","OPTIONS").contains(request.getMethod())) {
            String contentType=Optional.ofNullable(request.getContentType()).orElse("");
            boolean multipart=request.getRequestURI().equals("/api/uploads") && contentType.startsWith("multipart/form-data");
            boolean emptyCancel=request.getRequestURI().endsWith("/cancel") && request.getContentLengthLong()<=0;
            if(!contentType.startsWith("application/json") && !multipart && !emptyCancel) {reject(response,"API 写入请求须使用 application/json");return;}
            if(multipart && origin==null && fetchSite!=null) {reject(response,"浏览器上传缺少同源信息");return;}
        }
        response.setHeader("X-Content-Type-Options","nosniff");
        response.setHeader("X-Frame-Options","DENY");
        response.setHeader("Referrer-Policy","no-referrer");
        if(request.getRequestURI().startsWith("/api")) response.setHeader("Cache-Control","no-store");
        chain.doFilter(request,response);
    }
    private void reject(HttpServletResponse response,String message) throws IOException {
        response.setStatus(403);response.setContentType("application/json");response.setCharacterEncoding("UTF-8");response.getWriter().write(Json.write(Map.of("status",403,"error",message)));
    }
}
