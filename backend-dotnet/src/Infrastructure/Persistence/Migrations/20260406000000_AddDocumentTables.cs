using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddDocumentTables : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "document_tables",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    DocumentId = table.Column<Guid>(type: "uuid", nullable: false),
                    TableIndex = table.Column<int>(type: "integer", nullable: false),
                    Columns = table.Column<string[]>(type: "text[]", nullable: false),
                    RowsJson = table.Column<string>(type: "jsonb", nullable: false, defaultValue: "[]"),
                    Quality = table.Column<float>(type: "real", nullable: false),
                    RowCount = table.Column<int>(type: "integer", nullable: false),
                    DocTypeHint = table.Column<string>(type: "text", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_document_tables", x => x.Id);
                    table.ForeignKey(
                        name: "FK_document_tables_documents_DocumentId",
                        column: x => x.DocumentId,
                        principalTable: "documents",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_document_tables_DocumentId",
                table: "document_tables",
                column: "DocumentId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(name: "document_tables");
        }
    }
}
