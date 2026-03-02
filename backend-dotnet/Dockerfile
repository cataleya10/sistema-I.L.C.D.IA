# ─── .NET Backend API ───
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Restore
COPY Backend.slnx global.json ./
COPY src/Domain/Domain.csproj                     src/Domain/
COPY src/Application/Application.csproj           src/Application/
COPY src/Shared/Shared.csproj                     src/Shared/
COPY src/Infrastructure/Infrastructure.csproj     src/Infrastructure/
COPY src/Api/Api.csproj                           src/Api/
RUN dotnet restore Backend.slnx

# Build + Publish
COPY src/ src/
RUN dotnet publish src/Api/Api.csproj -c Release -o /app/publish --no-restore

# ─── Runtime ───
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app
COPY --from=build /app/publish .

ENV ASPNETCORE_URLS=http://+:5000
EXPOSE 5000

ENTRYPOINT ["dotnet", "Api.dll"]
