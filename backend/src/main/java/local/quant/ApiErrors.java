package local.quant;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import java.util.*;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(NoSuchElementException.class) public ResponseEntity<?> missing(NoSuchElementException e) {return error(HttpStatus.NOT_FOUND,e.getMessage());}
    @ExceptionHandler(IllegalArgumentException.class) public ResponseEntity<?> invalid(IllegalArgumentException e) {return error(HttpStatus.BAD_REQUEST,e.getMessage());}
    @ExceptionHandler(IllegalStateException.class) public ResponseEntity<?> conflict(IllegalStateException e) {return error(HttpStatus.CONFLICT,e.getMessage());}
    @ExceptionHandler(MaxUploadSizeExceededException.class) public ResponseEntity<?> tooLarge(MaxUploadSizeExceededException e) {return error(HttpStatus.PAYLOAD_TOO_LARGE,"上传文件超过 100 MB 限制");}
    private ResponseEntity<?> error(HttpStatus status,String message) {return ResponseEntity.status(status).body(Map.of("status",status.value(),"error",message==null?status.getReasonPhrase():message,"timestamp",MetadataStore.now()));}
}
