package com.sopiskill.core.sources;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Resolves deep-link citation URLs across arXiv (`/abs/` -> `/html/#S1`), Web (`#anchor`),
 * and uploaded PDFs (`canonicalUrl == null` -> inert pill).
 */
public final class CitationLinkResolver {

    private static final Pattern ARXIV_ABS = Pattern.compile("^https?://(?:www\\.)?arxiv\\.org/abs/([0-9]+\\.[0-9]+(?:v[0-9]+)?).*$");

    private CitationLinkResolver() {}

    public static String resolveDeepLink(String canonicalUrl, String sectionAnchor) {
        if (canonicalUrl == null || canonicalUrl.isBlank()) {
            return null; // Uploaded PDF -> inert pill
        }
        String cleanUrl = canonicalUrl.trim();
        String anchor = (sectionAnchor == null || sectionAnchor.isBlank())
                ? null
                : sectionAnchor.trim().replaceAll("^#+", "");

        Matcher arxiv = ARXIV_ABS.matcher(cleanUrl);
        if (arxiv.matches()) {
            String paperId = arxiv.group(1);
            String targetAnchor = anchor != null ? anchor : "S1";
            return "https://arxiv.org/html/" + paperId + "#" + targetAnchor;
        }

        int hashIdx = cleanUrl.indexOf('#');
        String base = hashIdx >= 0 ? cleanUrl.substring(0, hashIdx) : cleanUrl;
        return anchor != null ? base + "#" + anchor : base;
    }
}
