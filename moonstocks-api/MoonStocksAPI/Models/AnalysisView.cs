namespace MoonStocksAPI.Models;

public class AnalysisView(string tickerAndExchangeCode, string jsonReport, long generatedTime)
{
    public string TickerAndExchangeCode { get; set; } = tickerAndExchangeCode;
    public string JsonReport { get; set; } = jsonReport;
    public long GeneratedTime { get; set; } = generatedTime;
}