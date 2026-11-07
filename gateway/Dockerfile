FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre
RUN useradd --system --uid 10001 edge
WORKDIR /app
COPY --from=build /build/target/eka-edge-*.jar app.jar
USER edge
EXPOSE 8080 8081
ENTRYPOINT ["java", "-jar", "app.jar"]
