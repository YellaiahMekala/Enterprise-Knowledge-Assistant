package com.eka.ops.triage;

import com.eka.ops.alert.AlertmanagerPayload.Alert;
import java.util.List;

public record TriageReport(List<Alert> alerts, Triage triage, boolean aiAssisted, int toolCalls, String note) {}
