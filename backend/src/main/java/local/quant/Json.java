package local.quant;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

public final class Json {
    private static final ObjectMapper MAPPER = new ObjectMapper()
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
        .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
    private static final TypeReference<LinkedHashMap<String,Object>> MAP = new TypeReference<>() {};
    private Json() {}
    public static String write(Object value) {
        try { return MAPPER.writeValueAsString(value); }
        catch (IOException e) { throw new IllegalArgumentException("Invalid JSON value",e); }
    }
    public static Map<String,Object> object(String value) {
        try { return MAPPER.readValue(value,MAP); }
        catch (IOException e) { throw new IllegalArgumentException("JSON must be a valid object",e); }
    }
    public static Map<String,Object> read(Path path) throws IOException { return object(Files.readString(path)); }
    public static List<Map<String,Object>> array(Path path) throws IOException {
        return MAPPER.readValue(Files.readString(path),new TypeReference<>() {});
    }
    public static Map<String,Object> map(Object value) {
        if (!(value instanceof Map<?,?> m)) throw new IllegalArgumentException("Expected JSON object");
        Map<String,Object> copy = new LinkedHashMap<>();
        m.forEach((k,v)->copy.put(String.valueOf(k),v));
        return copy;
    }
    public static String text(Map<String,Object> map,String key,String fallback) {
        Object value=map.get(key); return value == null ? fallback : value.toString();
    }
    public static void assertFinite(Object value) {
        if(value instanceof Number n && !Double.isFinite(n.doubleValue())) throw new IllegalArgumentException("Nonfinite numeric result");
        if(value instanceof Map<?,?> m) m.values().forEach(Json::assertFinite);
        if(value instanceof Collection<?> c) c.forEach(Json::assertFinite);
    }
}
