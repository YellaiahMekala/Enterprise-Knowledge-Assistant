// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.triage;

import java.util.List;

/** What the model must return, as a record so the reply is parsed instead of scraped. */
public record Triage(String summary, String likelyCause, List<String> evidence, List<String> nextSteps) {}
