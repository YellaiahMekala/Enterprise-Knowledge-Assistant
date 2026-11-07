package com.eka.edge.security;

/** Who the caller is, as the core will see them: a pseudonymous id and a role. */
public record Identity(String userId, String role) {

    public static final String USER = "user";
    public static final String ADMIN = "admin";
}
