using MoonStocksAPI.Database;
using MoonStocksAPI.Models;

namespace MoonStocksAPI.Repository;

public class AnalysisRepository(MoonStocksDbContext dbContext)
{
    public List<AnalysisDbModel> GetLatestAnalyses()
    {
        return dbContext.Analyses
            .Where(a =>
                a.GeneratedTime ==
                dbContext.Analyses
                    .Where(b => b.TickerAndExchangeCode == a.TickerAndExchangeCode)
                    .Max(b => b.GeneratedTime))
            .OrderByDescending(x => x.GeneratedTime)
            .ToList();
    }

    public void AddAnalysis(AnalysisWrite newAnalysis, string tickerAndExchangeCode)
    {
        var analysisDbModel = new AnalysisDbModel
        {
            Id = Guid.NewGuid(),
            GeneratedTime = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
            JsonReport = newAnalysis.JsonReport,
            TickerAndExchangeCode = tickerAndExchangeCode
        };
        dbContext.Analyses.Add(analysisDbModel);
        dbContext.SaveChanges();
    }
    
}