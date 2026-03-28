<?php
function slugify($text) {
  $text = strtolower(trim($text));
  $text = preg_replace('~[^\pL\d]+~u', '-', $text);
  $text = iconv('utf-8', 'us-ascii//TRANSLIT', $text);
  $text = preg_replace('~[^-\w]+~', '', $text);
  $text = trim($text, '-');
  $text = preg_replace('~-+~', '-', $text);
  return $text ?: 'item';
}

function ip_hash() {
  $ip = $_SERVER['REMOTE_ADDR'] ?? '0.0.0.0';
  return hash('sha256', $ip . '|' . date('Y-m-d')); // muda por dia (privacidade)
}

function request_server_value($keys, $server = null) {
  $serverBag = is_array($server) ? $server : $_SERVER;
  foreach ((array) $keys as $key) {
    $value = trim((string) ($serverBag[$key] ?? ''));
    if ($value !== '') {
      return $value;
    }
  }
  return '';
}

function click_country_name_from_code($code) {
  $normalized = strtoupper(trim((string) $code));
  if ($normalized === '') {
    return '';
  }

  static $map = [
    'AR' => 'Argentina',
    'BO' => 'Bolivia',
    'BR' => 'Brasil',
    'CA' => 'Canada',
    'CL' => 'Chile',
    'CO' => 'Colombia',
    'DE' => 'Alemanha',
    'ES' => 'Espanha',
    'FR' => 'Franca',
    'GB' => 'Reino Unido',
    'IN' => 'India',
    'IT' => 'Italia',
    'JP' => 'Japao',
    'MX' => 'Mexico',
    'PE' => 'Peru',
    'PT' => 'Portugal',
    'PY' => 'Paraguai',
    'UY' => 'Uruguai',
    'US' => 'Estados Unidos',
  ];

  return $map[$normalized] ?? $normalized;
}

function click_location_context($server = null) {
  $countryCode = strtoupper(request_server_value([
    'HTTP_CF_IPCOUNTRY',
    'HTTP_GEOIP_COUNTRY_CODE',
    'GEOIP_COUNTRY_CODE',
    'HTTP_X_COUNTRY_CODE',
  ], $server));
  $countryName = request_server_value([
    'HTTP_GEOIP_COUNTRY_NAME',
    'GEOIP_COUNTRY_NAME',
    'HTTP_X_COUNTRY_NAME',
  ], $server);
  if ($countryName === '' && $countryCode !== '') {
    $countryName = click_country_name_from_code($countryCode);
  }

  $region = request_server_value([
    'HTTP_GEOIP_REGION_NAME',
    'GEOIP_REGION_NAME',
    'HTTP_X_REGION_NAME',
    'HTTP_X_REGION',
    'GEOIP_REGION',
  ], $server);
  $city = request_server_value([
    'HTTP_GEOIP_CITY',
    'GEOIP_CITY',
    'HTTP_X_CITY',
  ], $server);
  $localeHint = request_server_value(['HTTP_ACCEPT_LANGUAGE'], $server);

  $source = '';
  if ($countryCode !== '' || $countryName !== '' || $region !== '' || $city !== '') {
    $source = 'server_geo';
  }

  return [
    'country_code' => substr($countryCode, 0, 8),
    'country_name' => substr($countryName, 0, 80),
    'region_name' => substr($region, 0, 80),
    'city_name' => substr($city, 0, 80),
    'locale_hint' => substr($localeHint, 0, 80),
    'source' => $source,
  ];
}

function click_request_profile($userAgent = null, $requestMethod = null, $referer = null) {
  $ua = trim((string) ($userAgent ?? ($_SERVER['HTTP_USER_AGENT'] ?? '')));
  $method = strtoupper(trim((string) ($requestMethod ?? ($_SERVER['REQUEST_METHOD'] ?? 'GET'))));
  $ref = trim((string) ($referer ?? ($_SERVER['HTTP_REFERER'] ?? '')));
  $uaLower = strtolower($ua);

  if ($method === 'HEAD' || $method === 'OPTIONS') {
    return ['is_bot' => true, 'label' => 'bot', 'reason' => "Metodo {$method}"];
  }

  $namedPatterns = [
    'mj12bot' => 'MJ12Bot',
    'ahrefsbot' => 'AhrefsBot',
    'semrushbot' => 'SemrushBot',
    'googlebot' => 'Googlebot',
    'adsbot-google' => 'AdsBot Google',
    'bingbot' => 'Bingbot',
    'bingpreview' => 'BingPreview',
    'bytespider' => 'ByteSpider',
    'duckduckbot' => 'DuckDuckBot',
    'yandexbot' => 'YandexBot',
    'facebookexternalhit' => 'Facebook Preview',
    'facebot' => 'Facebook Bot',
    'meta-externalagent' => 'Meta External Agent',
    'whatsapp' => 'WhatsApp Preview',
    'telegrambot' => 'Telegram Bot',
    'discordbot' => 'Discord Bot',
    'linkedinbot' => 'LinkedIn Bot',
    'slackbot' => 'Slack Bot',
    'applebot' => 'Applebot',
    'lighthouse' => 'Lighthouse',
    'headlesschrome' => 'HeadlessChrome',
    'phantomjs' => 'PhantomJS',
    'curl/' => 'curl',
    'wget/' => 'wget',
    'python-requests' => 'Python Requests',
    'python-httpx' => 'Python HTTPX',
    'go-http-client' => 'Go HTTP Client',
  ];

  foreach ($namedPatterns as $pattern => $label) {
    if ($uaLower !== '' && str_contains($uaLower, $pattern)) {
      return ['is_bot' => true, 'label' => 'bot', 'reason' => $label];
    }
  }

  if ($uaLower === '') {
    return ['is_bot' => true, 'label' => 'bot', 'reason' => 'Sem user-agent'];
  }

  if (preg_match('/(^|[^a-z])(bot|crawler|spider|preview|scanner|scrapy|slurp)([^a-z]|$)/i', $uaLower)) {
    return ['is_bot' => true, 'label' => 'bot', 'reason' => 'Padrao generico de crawler'];
  }

  if ($ref !== '' && preg_match('~/(preview|crawler|bot)([/?#._-]|$)~i', $ref)) {
    return ['is_bot' => true, 'label' => 'bot', 'reason' => 'Referer de preview/crawler'];
  }

  return ['is_bot' => false, 'label' => 'human', 'reason' => 'Navegador comum'];
}

function tag_list_from_string($tags) {
  $items = array_filter(array_map('trim', explode(',', (string) $tags)));
  return array_values(array_unique($items));
}

function tag_url_encode($url) {
  $value = trim((string) $url);
  if ($value === '') {
    return '';
  }
  return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
}

function tag_url_decode($tags, $prefix) {
  $normalizedPrefix = (string) $prefix;
  if ($normalizedPrefix === '') {
    return '';
  }

  foreach (tag_list_from_string($tags) as $tag) {
    if (!str_starts_with($tag, $normalizedPrefix)) {
      continue;
    }

    $encoded = substr($tag, strlen($normalizedPrefix));
    if ($encoded === '') {
      continue;
    }

    $padding = strlen($encoded) % 4;
    if ($padding > 0) {
      $encoded .= str_repeat('=', 4 - $padding);
    }

    $decoded = base64_decode(strtr($encoded, '-_', '+/'), true);
    if ($decoded === false) {
      continue;
    }

    $url = trim((string) $decoded);
    if ($url !== '' && preg_match('~^https?://~i', $url)) {
      return $url;
    }
  }

  return '';
}

function tag_url_remove_prefixes($tags, $prefixes) {
  $normalizedPrefixes = array_values(array_filter(array_map('strval', (array) $prefixes)));
  if (!$normalizedPrefixes) {
    return trim((string) $tags);
  }

  $items = array_filter(tag_list_from_string($tags), static function ($tag) use ($normalizedPrefixes) {
    foreach ($normalizedPrefixes as $prefix) {
      if ($prefix !== '' && str_starts_with((string) $tag, $prefix)) {
        return false;
      }
    }
    return true;
  });

  return implode(',', $items);
}

function tag_url_upsert($tags, $prefix, $url) {
  $normalized = tag_url_remove_prefixes($tags, [$prefix]);
  $items = $normalized !== '' ? tag_list_from_string($normalized) : [];
  $encoded = tag_url_encode($url);
  if ($encoded !== '') {
    $items[] = (string) $prefix . $encoded;
  }
  return implode(',', array_values(array_unique($items)));
}

function h($s) {
  return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}
