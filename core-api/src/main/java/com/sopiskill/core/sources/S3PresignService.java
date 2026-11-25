package com.sopiskill.core.sources;

import com.sopiskill.core.config.SopiProperties;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.HexFormat;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Pure-Java AWS Signature Version 4 presigner for direct browser -> MinIO/S3 PDF uploads
 * (`POST /v1/sources/upload` -> browser `PUT` directly to MinIO without buffering 25MB in core-api RAM).
 */
@Service
public class S3PresignService {

    private static final Logger log = LoggerFactory.getLogger(S3PresignService.class);
    private static final DateTimeFormatter AMZ_DATE_FMT =
            DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC);
    private static final DateTimeFormatter DATE_STAMP_FMT =
            DateTimeFormatter.ofPattern("yyyyMMdd").withZone(ZoneOffset.UTC);

    private final SopiProperties props;
    private final HttpClient httpClient;
    private final AtomicBoolean bucketReady = new AtomicBoolean(false);

    public S3PresignService(SopiProperties props) {
        this.props = props;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    public String createPresignedPutUrl(String objectKey, int expiresSeconds) {
        ensureBucketExistsBestEffort();
        Instant now = Instant.now();
        String amzDate = AMZ_DATE_FMT.format(now);
        String dateStamp = DATE_STAMP_FMT.format(now);
        String region = props.s3Region() == null || props.s3Region().isBlank() ? "us-east-1" : props.s3Region();
        String bucket = props.s3Bucket();

        URI publicUri = URI.create(props.s3PublicEndpoint().replaceAll("/+$", ""));
        String host = publicUri.getHost() + (publicUri.getPort() > 0 ? ":" + publicUri.getPort() : "");
        String canonicalUri = "/" + bucket + "/" + encodePath(objectKey);
        String scope = dateStamp + "/" + region + "/s3/aws4_request";
        String credential = props.s3AccessKey() + "/" + scope;

        String canonicalQuery = "X-Amz-Algorithm=AWS4-HMAC-SHA256"
                + "&X-Amz-Credential=" + urlEncode(credential)
                + "&X-Amz-Date=" + amzDate
                + "&X-Amz-Expires=" + expiresSeconds
                + "&X-Amz-SignedHeaders=host";

        String canonicalHeaders = "host:" + host + "\n";
        String canonicalRequest = "PUT\n"
                + canonicalUri + "\n"
                + canonicalQuery + "\n"
                + canonicalHeaders + "\n"
                + "host\n"
                + "UNSIGNED-PAYLOAD";

        String stringToSign = "AWS4-HMAC-SHA256\n"
                + amzDate + "\n"
                + scope + "\n"
                + sha256Hex(canonicalRequest.getBytes(StandardCharsets.UTF_8));

        byte[] signingKey = getSignatureKey(props.s3SecretKey(), dateStamp, region, "s3");
        String signature = HexFormat.of().formatHex(hmacSha256(signingKey, stringToSign));

        return publicUri + canonicalUri + "?" + canonicalQuery + "&X-Amz-Signature=" + signature;
    }

    public void ensureBucketExistsBestEffort() {
        if (bucketReady.get()) return;
        try {
            Instant now = Instant.now();
            String amzDate = AMZ_DATE_FMT.format(now);
            String dateStamp = DATE_STAMP_FMT.format(now);
            String region = props.s3Region() == null || props.s3Region().isBlank() ? "us-east-1" : props.s3Region();
            URI internalUri = URI.create(props.s3Endpoint().replaceAll("/+$", ""));
            String host = internalUri.getHost() + (internalUri.getPort() > 0 ? ":" + internalUri.getPort() : "");
            String canonicalUri = "/" + props.s3Bucket();
            String payloadHash = sha256Hex(new byte[0]);
            String canonicalHeaders = "host:" + host + "\nx-amz-content-sha256:" + payloadHash + "\nx-amz-date:" + amzDate + "\n";
            String signedHeaders = "host;x-amz-content-sha256;x-amz-date";
            String canonicalRequest = "PUT\n" + canonicalUri + "\n\n" + canonicalHeaders + "\n" + signedHeaders + "\n" + payloadHash;
            String scope = dateStamp + "/" + region + "/s3/aws4_request";
            String stringToSign = "AWS4-HMAC-SHA256\n" + amzDate + "\n" + scope + "\n"
                    + sha256Hex(canonicalRequest.getBytes(StandardCharsets.UTF_8));
            String signature = HexFormat.of().formatHex(hmacSha256(getSignatureKey(props.s3SecretKey(), dateStamp, region, "s3"), stringToSign));
            String auth = "AWS4-HMAC-SHA256 Credential=" + props.s3AccessKey() + "/" + scope
                    + ", SignedHeaders=" + signedHeaders + ", Signature=" + signature;

            HttpRequest req = HttpRequest.newBuilder(URI.create(internalUri + canonicalUri))
                    .timeout(Duration.ofSeconds(5))
                    .header("x-amz-content-sha256", payloadHash)
                    .header("x-amz-date", amzDate)
                    .header("Authorization", auth)
                    .PUT(HttpRequest.BodyPublishers.noBody())
                    .build();
            HttpResponse<Void> resp = httpClient.send(req, HttpResponse.BodyHandlers.discarding());
            if (resp.statusCode() == 200 || resp.statusCode() == 409) {
                bucketReady.set(true);
            }
        } catch (Exception ex) {
            log.warn("s3_bucket_bootstrap_failed type={}", ex.getClass().getSimpleName());
        }
    }

    private static byte[] getSignatureKey(String key, String dateStamp, String region, String service) {
        byte[] kDate = hmacSha256(("AWS4" + key).getBytes(StandardCharsets.UTF_8), dateStamp);
        byte[] kRegion = hmacSha256(kDate, region);
        byte[] kService = hmacSha256(kRegion, service);
        return hmacSha256(kService, "aws4_request");
    }

    private static byte[] hmacSha256(byte[] key, String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key, "HmacSHA256"));
            return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static String sha256Hex(byte[] data) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static String urlEncode(String val) {
        return URLEncoder.encode(val, StandardCharsets.UTF_8).replace("+", "%20").replace("*", "%2A").replace("%7E", "~");
    }

    private static String encodePath(String key) {
        String[] segments = key.replaceAll("^/+", "").split("/");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < segments.length; i++) {
            if (i > 0) sb.append('/');
            sb.append(urlEncode(segments[i]));
        }
        return sb.toString();
    }
}
