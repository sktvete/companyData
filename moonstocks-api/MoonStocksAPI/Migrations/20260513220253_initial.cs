using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace MoonStocksAPI.Migrations
{
    /// <inheritdoc />
    public partial class initial : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Analyses",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uniqueidentifier", nullable: false),
                    TickerAndExchangeCode = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    JsonReport = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    GeneratedTime = table.Column<long>(type: "bigint", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Analyses", x => x.Id);
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "Analyses");
        }
    }
}
