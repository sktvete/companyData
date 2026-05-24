using Microsoft.AspNetCore.Mvc;
using MoonStocksAPI.Clients;
using MoonStocksAPI.Models;
using MoonStocksAPI.Repository;

namespace MoonStocksAPI.Controllers;

[ApiController]
[Route("api/analysis")]
public class AnalysisController(AnalysisRepository repository, AnalyzerClient analyzer) : ControllerBase
{
    [HttpGet("")]
    public ActionResult<List<AnalysisView>> GetAllAnalyses()
    {
        var latestAnalyses = repository.GetLatestAnalyses();
        var converted = latestAnalyses.ConvertAll(a => new AnalysisView(a.TickerAndExchangeCode, a.JsonReport, a.GeneratedTime));
        return converted;

    }

    [HttpPost("{tickerAndExchangeCode}")]
    public void CreateAnalysis(string tickerAndExchangeCode, AnalysisWrite newAnalysis)
    {
        repository.AddAnalysis(newAnalysis, tickerAndExchangeCode);

    }

    [HttpPost("{tickerAndExchangeCode}/trigger")]
    public async Task<IActionResult> TriggerAnalysis(string tickerAndExchangeCode, CancellationToken ct)
    {
        var response = await analyzer.TriggerAsync(tickerAndExchangeCode, ct);
        if (!response.IsSuccessStatusCode)
        {
            var body = await response.Content.ReadAsStringAsync(ct);
            return StatusCode((int)response.StatusCode, body);
        }
        return Accepted(new { status = "accepted", tickerAndExchangeCode });
    }
}