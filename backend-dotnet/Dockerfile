# ─── .NET Backend API ───
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

# Restore
COPY src/Domain/Domain.csproj                     src/Domain/
COPY src/Application/Application.csproj           src/Application/
COPY src/Shared/Shared.csproj                     src/Shared/
COPY src/Infrastructure/Infrastructure.csproj     src/Infrastructure/
COPY src/Api/Api.csproj                           src/Api/
RUN dotnet restore src/Api/Api.csproj

# Build + Publish
COPY src/ src/
RUN dotnet publish src/Api/Api.csproj -c Release -o /app/publish

# ─── Runtime ───
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && mkdir -p /app/storage /app/logs && chown -R appuser:appgroup /app
USER appuser

ENV ASPNETCORE_URLS=http://+:5000
EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=10s --retries=3 \
    CMD dotnet --list-runtimes > /dev/null && wget -q --spider http://localhost:5000/health || exit 1

ENTRYPOINT ["dotnet", "Api.dll"]
