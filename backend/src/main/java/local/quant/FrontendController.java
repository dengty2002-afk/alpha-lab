package local.quant;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
public class FrontendController {
    @GetMapping({"/","/data","/factors","/analysis","/experiments","/reports","/jobs","/compare"})
    public String frontend() {return "forward:/index.html";}
}
