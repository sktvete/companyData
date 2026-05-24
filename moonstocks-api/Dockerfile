FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /source

COPY MoonStocksAPI/*.csproj ./MoonStocksAPI/
RUN dotnet restore MoonStocksAPI/MoonStocksAPI.csproj

COPY MoonStocksAPI/. ./MoonStocksAPI/
WORKDIR /source/MoonStocksAPI
RUN dotnet publish -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app ./
ENTRYPOINT ["dotnet", "MoonStocksAPI.dll"]
