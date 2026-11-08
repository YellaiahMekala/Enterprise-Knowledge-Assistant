package com.eka.ops.triage;

import java.util.List;

/** What the model must return, as a record so the reply is parsed instead of scraped. */
public record Triage(String summary, String likelyCause, List<String> evidence, List<String> nextSteps) {}
