package com.sopiskill.core;

import com.sopiskill.core.config.SopiProperties;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;

@SpringBootApplication
@EnableConfigurationProperties(SopiProperties.class)
public class CoreApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(CoreApiApplication.class, args);
    }

    @Bean
    ApplicationRunner migrateOnlyExitRunner(
            ConfigurableApplicationContext context,
            @Value("${sopiskill.migrate-only:false}") boolean migrateOnly
    ) {
        return args -> {
            if (migrateOnly) {
                int code = SpringApplication.exit(context, () -> 0);
                System.exit(code);
            }
        };
    }
}
