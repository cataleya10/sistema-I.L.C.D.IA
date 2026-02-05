using System.Text.Json;
using Infrastructure;
using Api.Logging;
using Api.Middlewares;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using System.Threading.RateLimiting;
using Api.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using Shared.Options;
using System.Text;
using Shared.Json;
using System.Text.Json.Serialization;

var builder = WebApplication.CreateBuilder(args);

var logPath = builder.Configuration.GetValue<string>("Logging:FilePath") ?? "logs/api.log";
builder.Logging.AddProvider(new SimpleFileLoggerProvider(logPath));

builder.Services
    .AddControllers()
    .AddJsonOptions(options =>
    {
        options.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
        options.JsonSerializerOptions.DictionaryKeyPolicy = JsonNamingPolicy.SnakeCaseLower;
        options.JsonSerializerOptions.Converters.Add(
            new JsonStringEnumConverter(new UpperSnakeCaseNamingPolicy()));
    });

builder.Services.AddDataProtection();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(options =>
{
    options.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Name = "Authorization",
        Type = SecuritySchemeType.Http,
        Scheme = "Bearer",
        BearerFormat = "JWT",
        In = ParameterLocation.Header,
        Description = "JWT Authorization header using the Bearer scheme."
    });
    options.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecurityScheme
            {
                Reference = new OpenApiReference
                {
                    Type = ReferenceType.SecurityScheme,
                    Id = "Bearer"
                }
            },
            Array.Empty<string>()
        }
    });
    options.OperationFilter<Api.Swagger.FileUploadOperationFilter>();
});
builder.Services.AddHealthChecks();

builder.Services.Configure<UploadOptions>(
    builder.Configuration.GetSection(UploadOptions.SectionName));

builder.Services.Configure<JwtOptions>(
    builder.Configuration.GetSection(JwtOptions.SectionName));

builder.Services.PostConfigure<JwtOptions>(options =>
{
    foreach (var user in options.Users)
    {
        if (!string.IsNullOrWhiteSpace(user.Password) && string.IsNullOrWhiteSpace(user.PasswordHash))
        {
            user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(user.Password);
            user.Password = string.Empty;
        }
    }
});

builder.Services.Configure<SystemInfoOptions>(
    builder.Configuration.GetSection(SystemInfoOptions.SectionName));

builder.Services.Configure<ProcessingOptions>(
    builder.Configuration.GetSection(ProcessingOptions.SectionName));

builder.Services.Configure<RefreshTokenOptions>(
    builder.Configuration.GetSection(RefreshTokenOptions.SectionName));

builder.Services.Configure<CorsOptions>(
    builder.Configuration.GetSection(CorsOptions.SectionName));

builder.Services.Configure<RateLimitOptions>(
    builder.Configuration.GetSection(RateLimitOptions.SectionName));

builder.Services.AddSingleton<JwtTokenService>();
builder.Services.AddSingleton<RefreshTokenStore>();
builder.Services.AddSingleton<Api.Services.MetricsService>();
builder.Services.AddHostedService<Api.Services.DocumentProcessingWorker>();
builder.Services.AddHostedService<Api.Services.StorageCleanupWorker>();
builder.Services.AddHostedService<Api.Services.RefreshTokenCleanupWorker>();

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        var jwtOptions = builder.Configuration.GetSection(JwtOptions.SectionName).Get<JwtOptions>() ?? new JwtOptions();
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateIssuerSigningKey = true,
            ValidateLifetime = true,
            ValidIssuer = jwtOptions.Issuer,
            ValidAudience = jwtOptions.Audience,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtOptions.SigningKey))
        };
    });

builder.Services.AddAuthorization();

builder.Services.AddRateLimiter(options =>
{
    var rateOptions = builder.Configuration.GetSection(RateLimitOptions.SectionName).Get<RateLimitOptions>() ?? new RateLimitOptions();
    options.AddPolicy("user", context =>
    {
        var user = context.User;
        var username = user?.Identity?.Name ?? "anonymous";
        var role = user?.FindFirst(System.Security.Claims.ClaimTypes.Role)?.Value ?? "Anonymous";

        var permitLimit = role switch
        {
            "Admin" => rateOptions.AdminPermitLimit,
            "User" => rateOptions.UserPermitLimit,
            _ => rateOptions.AnonymousPermitLimit
        };

        var partitionKey = $"{role}:{username}";
        return RateLimitPartition.GetFixedWindowLimiter(partitionKey, _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = permitLimit,
            Window = TimeSpan.FromSeconds(rateOptions.WindowSeconds),
            QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
            QueueLimit = rateOptions.QueueLimit
        });
    });
});

builder.Services.AddCors(options =>
{
    var corsOptions = builder.Configuration.GetSection(CorsOptions.SectionName).Get<CorsOptions>() ?? new CorsOptions();
    options.AddPolicy("WebClient", policy =>
        policy.WithOrigins(corsOptions.AllowedOrigins)
            .AllowAnyHeader()
            .AllowAnyMethod());
});

builder.Services.AddInfrastructure(builder.Configuration);

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}
else
{
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseMiddleware<CorrelationIdMiddleware>();
app.UseMiddleware<ExceptionHandlingMiddleware>();
app.UseMiddleware<RequestLoggingMiddleware>();
app.UseMiddleware<SecurityHeadersMiddleware>();
app.UseCors("WebClient");
app.UseRateLimiter();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers().RequireRateLimiting("user");
app.MapHealthChecks("/health");

using (var scope = app.Services.CreateScope())
{
    var logger = scope.ServiceProvider.GetRequiredService<ILoggerFactory>().CreateLogger("DbInit");
    var configuration = scope.ServiceProvider.GetRequiredService<IConfiguration>();
    var provider = configuration.GetValue<string>("Database:Provider") ?? "Postgres";

    if (!string.Equals(provider, "InMemory", StringComparison.OrdinalIgnoreCase))
    {
        try
        {
            var db = scope.ServiceProvider.GetRequiredService<Infrastructure.Persistence.DocumentDbContext>();
            db.Database.Migrate();
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Database migration skipped or failed.");
        }
    }
}

app.Run();
