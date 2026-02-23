using Application.Interfaces;
using Infrastructure.Clients;
using Infrastructure.Persistence;
using Infrastructure.Services;
using Infrastructure.Storage;
using Application.Storage;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Shared.Options;

namespace Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<StorageOptions>(configuration.GetSection(StorageOptions.SectionName));

        var provider = configuration.GetValue<string>("Database:Provider") ?? "Postgres";

        services.AddDbContext<DocumentDbContext>(options =>
        {
            if (string.Equals(provider, "InMemory", StringComparison.OrdinalIgnoreCase))
            {
                options.UseInMemoryDatabase("ilcdia");
            }
            else
            {
                options.UseNpgsql(
                    configuration.GetConnectionString("Default"),
                    b => b.MigrationsAssembly(typeof(DocumentDbContext).Assembly.FullName));
            }
        });

        services.AddHttpContextAccessor();
        services.AddSingleton<IProcessingQueue, DocumentProcessingQueue>();
        services.AddSingleton<IProcessingTracker, ProcessingTracker>();
        services.AddScoped<IDocumentService, DocumentService>();
        services.AddScoped<CSharpAiClient>();
        services.AddHttpClient<PythonAiClient>();

        var aiProvider = configuration.GetValue<string>("AiEngine:Provider") ?? "Python";
        if (string.Equals(aiProvider, "CSharp", StringComparison.OrdinalIgnoreCase))
        {
            services.AddScoped<IPythonAiClient>(sp => sp.GetRequiredService<CSharpAiClient>());
        }
        else if (string.Equals(aiProvider, "Hybrid", StringComparison.OrdinalIgnoreCase))
        {
            services.AddScoped<IPythonAiClient, HybridAiClient>();
        }
        else
        {
            services.AddScoped<IPythonAiClient>(sp => sp.GetRequiredService<PythonAiClient>());
        }

        services.AddSingleton<IFileStorage, LocalFileStorage>();

        return services;
    }
}
