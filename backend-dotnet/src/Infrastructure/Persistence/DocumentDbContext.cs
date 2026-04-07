using Domain.Entities;
using Domain.Enums;
using System.Text.Json;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using Microsoft.EntityFrameworkCore;

namespace Infrastructure.Persistence;

public class DocumentDbContext : DbContext
{
    public DocumentDbContext(DbContextOptions<DocumentDbContext> options) : base(options)
    {
    }

    public DbSet<Document> Documents => Set<Document>();
    public DbSet<DocumentField> DocumentFields => Set<DocumentField>();
    public DbSet<DocumentTable> DocumentTables => Set<DocumentTable>();
    public DbSet<ProcessingLog> ProcessingLogs => Set<ProcessingLog>();
    public DbSet<ModelVersion> ModelVersions => Set<ModelVersion>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Document>(entity =>
        {
            entity.ToTable("documents");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.Status).HasConversion<string>();
            entity.Property(x => x.DocumentType).HasConversion<string>();
            entity.Property(x => x.Confidence).HasPrecision(5, 2);
            entity.HasIndex(x => x.Status);
            entity.HasIndex(x => x.DocumentType);
            entity.HasIndex(x => x.UploadedAt);
            entity.HasMany(x => x.Fields)
                .WithOne(x => x.Document)
                .HasForeignKey(x => x.DocumentId);
            entity.HasMany(x => x.ProcessingLogs)
                .WithOne(x => x.Document)
                .HasForeignKey(x => x.DocumentId);
            entity.HasMany(x => x.Tables)
                .WithOne(x => x.Document)
                .HasForeignKey(x => x.DocumentId);
        });

        modelBuilder.Entity<DocumentField>(entity =>
        {
            entity.ToTable("document_fields");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.ValidationErrors).HasColumnType("text[]");
            entity.Property(x => x.SourceBbox).HasColumnType("integer[]");
            entity.HasIndex(x => x.DocumentId);
            entity.HasIndex(x => x.FieldKey);
        });

        modelBuilder.Entity<DocumentTable>(entity =>
        {
            entity.ToTable("document_tables");
            entity.HasKey(x => x.Id);
            entity.Property(x => x.Columns).HasColumnType("text[]");
            if (!Database.IsInMemory())
            {
                entity.Property(x => x.RowsJson).HasColumnType("jsonb");
            }
            entity.HasIndex(x => x.DocumentId);
        });

        modelBuilder.Entity<ProcessingLog>(entity =>
        {
            entity.ToTable("processing_logs");
            entity.HasKey(x => x.Id);
        });

        modelBuilder.Entity<ModelVersion>(entity =>
        {
            entity.ToTable("model_versions");
            entity.HasKey(x => x.Id);
            if (Database.IsInMemory())
            {
                entity.Ignore(x => x.Metrics);
            }
            else
            {
                var jsonConverter = new ValueConverter<JsonDocument?, string?>(
                    v => v == null ? null : v.RootElement.GetRawText(),
                    v => string.IsNullOrWhiteSpace(v) ? null : JsonDocument.Parse(v, new JsonDocumentOptions()));

                entity.Property(x => x.Metrics)
                    .HasConversion(jsonConverter)
                    .HasColumnType("jsonb");
            }
        });
    }
}
