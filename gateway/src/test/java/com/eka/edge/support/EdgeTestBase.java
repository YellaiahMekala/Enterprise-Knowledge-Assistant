// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
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
