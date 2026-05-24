namespace MoonStocksAPI.Models;

public class AnalysisWrite(string jsonReport)
{
    public string JsonReport { get; set; } = jsonReport;
}