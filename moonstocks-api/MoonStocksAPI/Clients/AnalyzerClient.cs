namespace MoonStocksAPI.Clients;

public sealed class AnalyzerClient(HttpClient httpClient, IConfiguration configuration)
{
    private readonly string _baseUrl = configuration["Analyzer:BaseUrl"] ?? "";
    private readonly string _apiKey = configuration["Analyzer:ApiKey"] ?? "";

    public async Task<HttpResponseMessage> TriggerAsync(string tickerAndExchangeCode, CancellationToken ct)
    {
        var url = $"{_baseUrl.TrimEnd('/')}/{tickerAndExchangeCode}";
        using var request = new HttpRequestMessage(HttpMethod.Post, url);
        request.Headers.Add("X-API-Key", _apiKey);
        return await httpClient.SendAsync(request, ct);
    }
}
