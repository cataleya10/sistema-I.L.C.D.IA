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

        services.AddSingleton<IProcessingQueue, DocumentProcessingQueue>();
        services.AddScoped<IDocumentService, DocumentService>();
        services.AddHttpClient<IPythonAiClient, PythonAiClient>();
        services.AddSingleton<IFileStorage, LocalFileStorage>();

        return services;
    }
}
