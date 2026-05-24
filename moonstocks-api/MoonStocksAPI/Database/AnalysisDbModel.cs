namespace MoonStocksAPI.Database;

public class AnalysisDbModel
{
    public Guid Id { get; set; }
    public string TickerAndExchangeCode { get; set; }
    public string JsonReport { get; set; }
    public long GeneratedTime { get; set; } // unix

}