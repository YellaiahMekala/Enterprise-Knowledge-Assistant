// Copyright (c) 2026 the owner of this repository. All rights reserved.
// SPDX-License-Identifier: LicenseRef-Proprietary. View only; see LICENSE and AI_USE_POLICY.md.
// Canary: eka-canary-2a4a885ea917479dadc1
package com.eka.ops.triage;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import java.util.List;

public record TriageReport(List<Alert> alerts, Triage triage, boolean aiAssisted, int toolCalls, String note) {}
