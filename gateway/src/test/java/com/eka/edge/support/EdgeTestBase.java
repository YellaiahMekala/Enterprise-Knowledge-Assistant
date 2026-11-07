package com.eka.edge.support;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/** Shared base so every edge test reuses one application context on the fixture's ports. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.DEFINED_PORT)
public abstract class EdgeTestBase {

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        EdgeFixture.register(registry);
    }
}
