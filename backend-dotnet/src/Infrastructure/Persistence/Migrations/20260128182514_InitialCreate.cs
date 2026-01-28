using System;
using System.Text.Json;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class InitialCreate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "documents",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    OriginalFilename = table.Column<string>(type: "text", nullable: false),
                    StoredFilename = table.Column<string>(type: "text", nullable: false),
                    FilePath = table.Column<string>(type: "text", nullable: false),
                    MimeType = table.Column<string>(type: "text", nullable: false),
                    FileSize = table.Column<long>(type: "bigint", nullable: false),
                    Status = table.Column<string>(type: "text", nullable: false),
                    DocumentType = table.Column<string>(type: "text", nullable: false),
                    Confidence = table.Column<decimal>(type: "numeric(5,2)", precision: 5, scale: 2, nullable: true),
                    UploadedBy = table.Column<string>(type: "text", nullable: true),
                    UploadedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    ProcessedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    ModelVersion = table.Column<string>(type: "text", nullable: true),
                    PipelineVersion = table.Column<string>(type: "text", nullable: true),
                    NeedsReview = table.Column<bool>(type: "boolean", nullable: false),
                    ErrorMessage = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_documents", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "model_versions",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    ModelType = table.Column<string>(type: "text", nullable: false),
                    Version = table.Column<string>(type: "text", nullable: false),
                    TrainedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    Metrics = table.Column<JsonDocument>(type: "jsonb", nullable: true),
                    Notes = table.Column<string>(type: "text", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_model_versions", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "document_fields",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    DocumentId = table.Column<Guid>(type: "uuid", nullable: false),
                    FieldKey = table.Column<string>(type: "text", nullable: false),
                    FieldLabel = table.Column<string>(type: "text", nullable: false),
                    FieldValue = table.Column<string>(type: "text", nullable: true),
                    Confidence = table.Column<decimal>(type: "numeric", nullable: false),
                    IsValid = table.Column<bool>(type: "boolean", nullable: false),
                    ValidationErrors = table.Column<string[]>(type: "text[]", nullable: false),
                    SourcePage = table.Column<int>(type: "integer", nullable: true),
                    SourceBbox = table.Column<int[]>(type: "integer[]", nullable: true),
                    Corrected = table.Column<bool>(type: "boolean", nullable: false),
                    CorrectedValue = table.Column<string>(type: "text", nullable: true),
                    CorrectedBy = table.Column<string>(type: "text", nullable: true),
                    CorrectedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_document_fields", x => x.Id);
                    table.ForeignKey(
                        name: "FK_document_fields_documents_DocumentId",
                        column: x => x.DocumentId,
                        principalTable: "documents",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "processing_logs",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    DocumentId = table.Column<Guid>(type: "uuid", nullable: false),
                    Stage = table.Column<string>(type: "text", nullable: false),
                    Level = table.Column<string>(type: "text", nullable: false),
                    Message = table.Column<string>(type: "text", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_processing_logs", x => x.Id);
                    table.ForeignKey(
                        name: "FK_processing_logs_documents_DocumentId",
                        column: x => x.DocumentId,
                        principalTable: "documents",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_document_fields_DocumentId",
                table: "document_fields",
                column: "DocumentId");

            migrationBuilder.CreateIndex(
                name: "IX_document_fields_FieldKey",
                table: "document_fields",
                column: "FieldKey");

            migrationBuilder.CreateIndex(
                name: "IX_documents_DocumentType",
                table: "documents",
                column: "DocumentType");

            migrationBuilder.CreateIndex(
                name: "IX_documents_Status",
                table: "documents",
                column: "Status");

            migrationBuilder.CreateIndex(
                name: "IX_documents_UploadedAt",
                table: "documents",
                column: "UploadedAt");

            migrationBuilder.CreateIndex(
                name: "IX_processing_logs_DocumentId",
                table: "processing_logs",
                column: "DocumentId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "document_fields");

            migrationBuilder.DropTable(
                name: "model_versions");

            migrationBuilder.DropTable(
                name: "processing_logs");

            migrationBuilder.DropTable(
                name: "documents");
        }
    }
}
