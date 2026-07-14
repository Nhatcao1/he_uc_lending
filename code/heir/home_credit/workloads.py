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

