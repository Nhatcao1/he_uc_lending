"""Notebook-aligned Home Credit EDA workload definitions for HEIR experiments."""

from __future__ import annotations

MISSING_BUCKET = "__MISSING__"

INCOME_TYPE_LABELS = [
    "Working",
    "Commercial associate",
    "Pensioner",
    "State servant",
    "Unemployed",
    "Student",
    "Businessman",
]

FAMILY_STATUS_LABELS = [
    "Married",
    "Single / not married",
    "Civil marriage",
    "Separated",
    "Widow",
]

OCCUPATION_TYPE_LABELS = [
    "Laborers",
    "Sales staff",
    "Core staff",
    "Managers",
    "Drivers",
    "High skill tech staff",
    "Accountants",
    "Medicine staff",
    "Security staff",
    "Cooking staff",
    "Cleaning staff",
    "Private service staff",
    "Low-skill Laborers",
    "Waiters/barmen staff",
    "Secretaries",
    "Realty agents",
]

EDUCATION_TYPE_LABELS = [
    "Secondary / secondary special",
    "Higher education",
    "Incomplete higher",
    "Lower secondary",
    "Academic degree",
]

HOUSING_TYPE_LABELS = [
    "House / apartment",
    "With parents",
    "Municipal apartment",
    "Rented apartment",
    "Office apartment",
]

ORGANIZATION_TYPE_LABELS = [
    "Business Entity Type 3",
    "XNA",
    "Self-employed",
    "Other",
    "Medicine",
    "Business Entity Type 2",
    "Government",
    "School",
    "Trade: type 7",
    "Kindergarten",
    "Construction",
    "Business Entity Type 1",
    "Transport: type 4",
    "Trade: type 3",
    "Industry: type 9",
    "Industry: type 3",
    "Security",
    "Housing",
    "Industry: type 11",
    "Military",
    "Bank",
    "Agriculture",
    "Police",
    "Transport: type 2",
    "Postal",
    "Security Ministries",
    "Trade: type 2",
    "Restaurant",
    "Services",
    "University",
    "Industry: type 7",
    "Transport: type 3",
    "Industry: type 4",
    "Hotel",
    "Electricity",
    "Industry: type 1",
    "Trade: type 6",
    "Industry: type 5",
    "Insurance",
    "Telecom",
    "Emergency",
    "Industry: type 2",
    "Advertising",
    "Realtor",
    "Culture",
    "Industry: type 12",
    "Trade: type 1",
    "Mobile",
    "Legal Services",
    "Cleaning",
    "Transport: type 1",
    "Industry: type 6",
    "Industry: type 10",
]

SUITE_TYPE_LABELS = [
    "Unaccompanied",
    "Family",
    "Spouse, partner",
    "Children",
    "Other_B",
    "Other_A",
    "Group of people",
]

TARGET_GROUP_WORKLOADS = {
    "app_target_by_income_type": {
        "section": "5.14.1",
        "title": "Income Type by Target",
        "column": "NAME_INCOME_TYPE",
        "labels": INCOME_TYPE_LABELS,
    },
    "app_target_by_family_status": {
        "section": "5.14.2",
        "title": "Family Status by Target",
        "column": "NAME_FAMILY_STATUS",
        "labels": FAMILY_STATUS_LABELS,
    },
    "app_target_by_occupation_type": {
        "section": "5.14.3",
        "title": "Occupation by Target",
        "column": "OCCUPATION_TYPE",
        "labels": OCCUPATION_TYPE_LABELS,
    },
    "app_target_by_education_type": {
        "section": "5.14.4",
        "title": "Education by Target",
        "column": "NAME_EDUCATION_TYPE",
        "labels": EDUCATION_TYPE_LABELS,
    },
    "app_target_by_housing_type": {
        "section": "5.14.5",
        "title": "Housing Type by Target",
        "column": "NAME_HOUSING_TYPE",
        "labels": HOUSING_TYPE_LABELS,
    },
    "app_target_by_organization_type": {
        "section": "5.14.6",
        "title": "Organization Type by Target",
        "column": "ORGANIZATION_TYPE",
        "labels": ORGANIZATION_TYPE_LABELS,
    },
    "app_target_by_suite_type": {
        "section": "5.14.7",
        "title": "Suite Type by Target",
        "column": "NAME_TYPE_SUITE",
        "labels": SUITE_TYPE_LABELS,
    },
}

APPLICATION_CATEGORY_WORKLOADS = {
    "app_suite_type": {
        "section": "5.4",
        "title": "Who Accompanied the Client",
        "column": "NAME_TYPE_SUITE",
    },
    "app_target_balance": {
        "section": "5.5",
        "title": "Target Balance",
        "column": "TARGET",
    },
    "app_loan_type": {
        "section": "5.6",
        "title": "Application Contract Type",
        "column": "NAME_CONTRACT_TYPE",
    },
    "app_own_car": {
        "section": "5.7",
        "title": "Applicant Owns a Car",
        "column": "FLAG_OWN_CAR",
    },
    "app_own_realty": {
        "section": "5.7",
        "title": "Applicant Owns Realty",
        "column": "FLAG_OWN_REALTY",
    },
}

# Notebook section 5.15 runs categorical distributions over previous_application.
# High-cardinality columns use the notebook-friendly top-K plus __OTHER__ view.
PREVIOUS_CATEGORY_WORKLOADS = {
    "prev_contract_type": {"section": "5.15.1", "title": "Previous Contract Type", "column": "NAME_CONTRACT_TYPE"},
    "prev_weekday_process_start": {"section": "5.15.2", "title": "Previous Application Weekday", "column": "WEEKDAY_APPR_PROCESS_START"},
    "prev_cash_loan_purpose": {"section": "5.15.3", "title": "Previous Cash Loan Purpose", "column": "NAME_CASH_LOAN_PURPOSE", "top_k": 20},
    "prev_contract_status": {"section": "5.15.4", "title": "Previous Contract Status", "column": "NAME_CONTRACT_STATUS"},
    "prev_payment_type": {"section": "5.15.5", "title": "Previous Payment Type", "column": "NAME_PAYMENT_TYPE"},
    "prev_reject_reason": {"section": "5.15.6", "title": "Previous Reject Reason", "column": "CODE_REJECT_REASON"},
    "prev_suite_type": {"section": "5.15.7", "title": "Previous Suite Type", "column": "NAME_TYPE_SUITE"},
    "prev_client_type": {"section": "5.15.8", "title": "Previous Client Type", "column": "NAME_CLIENT_TYPE"},
    "prev_goods_category": {"section": "5.15.9", "title": "Previous Goods Category", "column": "NAME_GOODS_CATEGORY", "top_k": 25},
    "prev_portfolio": {"section": "5.15.10", "title": "Previous Portfolio", "column": "NAME_PORTFOLIO"},
    "prev_product_type": {"section": "5.15.11", "title": "Previous Product Type", "column": "NAME_PRODUCT_TYPE"},
    "prev_channel_type": {"section": "5.15.12", "title": "Previous Channel Type", "column": "CHANNEL_TYPE"},
    "prev_seller_industry": {"section": "5.15.13", "title": "Previous Seller Industry", "column": "NAME_SELLER_INDUSTRY"},
    "prev_yield_group": {"section": "5.15.14", "title": "Previous Yield Group", "column": "NAME_YIELD_GROUP"},
    "prev_product_combination": {"section": "5.15.15", "title": "Previous Product Combination", "column": "PRODUCT_COMBINATION", "top_k": 25},
    "prev_insured_on_approval": {"section": "5.15.16", "title": "Previous Insured on Approval", "column": "NFLAG_INSURED_ON_APPROVAL"},
}

HEIR_WORKLOADS = {
    **APPLICATION_CATEGORY_WORKLOADS,
    **TARGET_GROUP_WORKLOADS,
    **PREVIOUS_CATEGORY_WORKLOADS,
}
