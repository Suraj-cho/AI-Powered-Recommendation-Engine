# AI-Powered Listing Recommendation Engine

## Testing Report

### 1. Project Overview

The AI-Powered Listing Recommendation Engine understands users' natural-language requests and recommends suitable listings from a structured database.

The system supports multiple listing categories, including rooms, cars, hotels, and venues. It considers user requirements such as location, budget, availability, capacity, and features.

### 2. Testing Objectives

- Verify natural-language query understanding.
- Validate filtering based on mandatory constraints.
- Test feature and attribute matching.
- Evaluate ranking based on user preferences.
- Verify handling of edge cases and no-match scenarios.

### 3. Test Case Details

#### Section 1: Basic Queries

**Purpose:** Verify that the system understands basic user requirements.

**Tested Queries:**

- `Find a room in Pune under 7000`
- `I need a car in Pune`

**Result:** Both tested queries returned correct answers.

#### Section 2: Hard Constraints

**Purpose:** Verify mandatory conditions such as budget, location, availability, and capacity.

**Tested Queries:**

- `Find a car in Pune priced more than 5000 per day`
- `Find an available car in Pune with 7 seats`

**Result:** Both tested queries returned correct answers.

#### Section 3: Features and Attributes

**Purpose:** Verify matching of listing attributes and tags.

**Tested Queries:**

- `Find a car with sunroof`
- `Find an automatic diesel car with sunroof`

**Result:** Both tested queries returned correct answers.

#### Section 4: Soft Preferences and Ranking

**Purpose:** Verify whether the system considers user preferences when recommending listings.

**Tested Queries:**

- `Find a car in Mumbai, preferably automatic with sunroof`
- `Find a hotel in Goa, preferably with a high rating and pool`

**Result:** Both tested queries returned correct answers.

#### Section 5: Edge Cases

**Purpose:** Verify how the system handles no-match requests, location mismatches, vague queries, availability, and capacity constraints.

**Test Case 1: No-Match Scenario**

Query: `Find a car in Pune under 1000`

Expected Behaviour: Return an appropriate no-match response.

Result: Accepted.

**Test Case 2: Location Mismatch**

Query: `Find a room in Delhi`

Expected Behaviour: Handle the location mismatch appropriately.

Result: Accepted.

**Test Case 3: Vague Query**

Query: `I need something good and affordable`

Expected Behaviour: Handle the vague request appropriately, ideally by asking a clarifying question.

Result: Accepted.

**Test Case 4: Availability and Feature Filtering**

Query: `Find an available car in Goa with sunroof`

Expected Behaviour: Check availability and feature constraints.

Result: Accepted.

**Test Case 5: Capacity Constraint**

Query: `Find a venue in Pune for 1000 people`

Expected Behaviour: Handle the capacity constraint and avoid unsuitable recommendations.

Result: Accepted.

**Test Case 6: Multiple Constraints**

Query: `Find a hotel in Pune with a swimming pool under 1000`

Expected Behaviour: Handle combined constraints and return an appropriate no-match response when no listing satisfies them.

Result: Accepted.

### 4. Overall Outcome

The tested queries returned correct answers according to the manual testing performed. All six edge-case tests were reported as accepted.

The initial testing indicates that the prototype can handle the tested natural-language requests, listing constraints, preferences, and edge cases.

**Testing Method:** Manual Testing

**Edge Cases Accepted:** 6 out of 6 tested edge cases.



