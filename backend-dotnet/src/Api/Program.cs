using System.Text.Json;
using Infrastructure;
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

builder.Services
    .AddControllers()
    .AddJsonOptions(options =>
    {
        options.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
        options.JsonSerializerOptions.DictionaryKeyPolicy = JsonNamingPolicy.SnakeCaseLower;
        options.JsonSerializerOptions.Converters.Add(
            new JsonStringEnumConverter(new UpperSnakeCaseNamingPolicy()));
    });

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
});
builder.Services.AddHealthChecks();

builder.Services.Configure<UploadOptions>(
    builder.Configuration.GetSection(UploadOptions.SectionName));

builder.Services.Configure<JwtOptions>(
    builder.Configuration.GetSection(JwtOptions.SectionName));

builder.Services.Configure<SystemInfoOptions>(
    builder.Configuration.GetSection(SystemInfoOptions.SectionName));

builder.Services.AddSingleton<JwtTokenService>();
builder.Services.AddSingleton<Api.Services.MetricsService>();

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
    options.AddFixedWindowLimiter("fixed", limiterOptions =>
    {
        limiterOptions.PermitLimit = 100;
        limiterOptions.Window = TimeSpan.FromMinutes(1);
        limiterOptions.QueueProcessingOrder = QueueProcessingOrder.OldestFirst;
        limiterOptions.QueueLimit = 20;
    });
});

builder.Services.AddCors(options =>
{
    options.AddPolicy("WebClient", policy =>
        policy.WithOrigins("http://localhost:4200")
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

app.UseHttpsRedirection();
app.UseMiddleware<CorrelationIdMiddleware>();
app.UseMiddleware<RequestLoggingMiddleware>();
app.UseMiddleware<SecurityHeadersMiddleware>();
app.UseCors("WebClient");
app.UseRateLimiter();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers().RequireRateLimiting("fixed");
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
