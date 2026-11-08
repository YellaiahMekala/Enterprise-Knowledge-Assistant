package com.eka.ops;

import com.eka.ops.config.OpsProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(OpsProperties.class)
public class OpsAgentApplication {

    public static void main(String[] args) {
        SpringApplication.run(OpsAgentApplication.class, args);
    }
}
