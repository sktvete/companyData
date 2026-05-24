using Microsoft.EntityFrameworkCore;

namespace MoonStocksAPI.Database;

public class MoonStocksDbContext : DbContext
{
    public MoonStocksDbContext(DbContextOptions options) : base(options)
    {
        
    }

    public DbSet<AnalysisDbModel> Analyses { get; set; }

}