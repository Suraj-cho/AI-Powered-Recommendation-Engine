(venv) C:\Users\shashi\Desktop\Recommendation_engine>python recommender.py
C:\Users\shashi\Desktop\Recommendation_engine\recommender.py:244: LangGraphDeprecatedSinceV10: create_react_agent has been moved to `langchain.agents`. Please update your import to `from langchain.agents import create_agent`. Deprecated in LangGraph V1.0 to be removed in V2.0.
  retrieval_agent = create_react_agent(
Listing Recommendation Engine (type 'exit' to quit)
Categories in database: car, hotel, room, venue

You: I want a car priced more than 5000 in Pune with sunroof

[1/4] understand_query ...
      category=car | hard=3 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 1 candidates

[3/4] validate_results ...
      valid=1 rejected=0 relevant=True

[4/4] rank_and_respond ...

============================================================
Top 1 recommendation(s):

1. Toyota Fortuner  (Pune)
   Rs 5,500 per day | capacity 7 | {"fuel": "diesel", "transmission": "automatic", "seats": 7, "tags": ["suv", "luxury", "sunroof"]}
   Why: Meets: location = Pune, price > 5000, tags contains sunroof
============================================================

You: Suggest a venue in Mumbai

[1/4] understand_query ...
      category=venue | hard=1 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 2 candidates

[3/4] validate_results ...
      valid=2 rejected=0 relevant=True

[4/4] rank_and_respond ...

============================================================
Top 2 recommendation(s):

1. Small Party Hall  (Mumbai)
   Rs 30,000 per day | capacity 50 | {"indoor": true, "tags": ["ac", "sound system"]}
   Why: Meets: location = Mumbai
2. Rooftop Party Space  (Mumbai)
   Rs 60,000 per day | capacity 100 | {"indoor": false, "tags": ["dj", "bar", "city view"]}
   Why: Meets: location = Mumbai
     Find an available room in Pune under 6000
Your request is broad. Could you tell me the expected capacity and budget for the venue?
[1/4] understand_query ...applied): capacity, price, date
      category=room | hard=3 | soft=0=======================

[2/4] retrieve_listings (attempt 1) ...
      fetched 1 candidates

[3/4] validate_results ...
      valid=1 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 1 candidates

[3/4] validate_results ...
      valid=1 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 1 candidates

[3/4] validate_results ...
      valid=1 rejected=0 relevant=False

[4/4] rank_and_respond ...

============================================================
Top 1 recommendation(s):

1. Budget Single Room Kothrud  (Pune)
   Rs 5,000 per month | capacity 1 | {"furnished": false, "bathroom": "shared", "tags": ["wifi", "near bus stop"]}
   Why: Meets: location = Pune, price < 6000, available = True
=====Find a furnished room in Pune with wifi and AC=========

[1/4] understand_query ...
      category=room | hard=4 | soft=0
You: 
[2/4] retrieve_listings (attempt 1) ...
      fetched 3 candidates

[3/4] validate_results ...
      valid=3 rejected=0 relevant=True

[4/4] rank_and_respond ...

============================================================
Top 3 recommendation(s):

1. Furnished 1BHK near Station  (Pune)
   Rs 6,500 per month | capacity 2 | {"furnished": true, "bathroom": "attached", "tags": ["wifi", "ac", "near metro"]}
   Why: Meets: location = Pune, furnished = True, tags contains wifi, tags contains ac
2. Spacious Room Hinjewadi  (Pune)
   Rs 7,500 per month | capacity 2 | {"furnished": true, "bathroom": "attached", "tags": ["wifi", "ac", "parking", "gym"]}
   Why: Meets: location = Pune, furnished = True, tags contains wifi, tags contains ac
3. Studio Apartment Baner  (Pune)
   Rs 9,500 per month | capacity 2 | {"furnished": true, "bathroom": "attached", "tags": ["wifi", "ac", "balcony", "parking"]}
   Why: Meets: location = Pune, furnished = True, tags contains wifi, tags contains ac
Details not given (so not applied): budget, capacity
============================================================

You: Find a car in Mumbai, preferably automatic with sunroof

[1/4] understand_query ...
      category=car | hard=1 | soft=2

[2/4] retrieve_listings (attempt 1) ...
      fetched 2 candidates

[3/4] validate_results ...
      valid=2 rejected=0 relevant=True

[4/4] rank_and_respond ...

============================================================
Top 2 recommendation(s):

1. Hyundai Creta  (Mumbai)
   Rs 2,800 per day | capacity 5 | {"fuel": "diesel", "transmission": "automatic", "seats": 5, "tags": ["suv", "sunroof"]}
   Why: Meets: location = Mumbai
2. Mahindra XUV700  (Mumbai)
   Rs 4,200 per day | capacity 7 | {"fuel": "diesel", "transmission": "automatic", "seats": 7, "tags": ["suv", "sunroof", "adas"]}
   Why: Meets: location = Mumbai
Details not given (so not applied): budget, capacity
============================================================

You: Find a car in Pune under 1000

[1/4] understand_query ...
      category=car | hard=2 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[4/4] rank_and_respond ...

============================================================
No listing meets all your requirements.

Closest options (each misses exactly ONE requirement):
1. Maruti Swift  (Pune) - Rs 1,800 per day
   Misses: price < 1000 (actual: 1800.0)
2. Toyota Innova Crysta  (Pune) - Rs 3,500 per day
   Misses: price < 1000 (actual: 3500.0)
3. Toyota Fortuner  (Pune) - Rs 5,500 per day
   Misses: price < 1000 (actual: 5500.0)

Tip: relax that requirement to get these options.
============================================================

You: I need something good and affordable

[1/4] understand_query ...
      category=None | hard=0 | soft=0

[4/4] rank_and_respond ...

============================================================
I couldn't tell what kind of listing you're looking for.
I can search: car, hotel, room, venue.
Could you specify what you are looking for (e.g., car, hotel, room, or venue), the location, and your budget?
============================================================

You: Find a room in Delhi

[1/4] understand_query ...
      category=room | hard=1 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[4/4] rank_and_respond ...

============================================================
Note: your requirements seem to conflict. Rooms are not available in Delhi according to the dataset; available locations are Bangalore, Mumbai, Nashik, and Pune.
No listing meets all your requirements.

Closest options (each misses exactly ONE requirement):
1. Student Room College Road  (Nashik) - Rs 4,500 per month
   Misses: location = Delhi (actual: Nashik)
2. Budget Single Room Kothrud  (Pune) - Rs 5,000 per month
   Misses: location = Delhi (actual: Pune)
3. Shared Room Borivali  (Mumbai) - Rs 6,000 per month
   Misses: location = Delhi (actual: Mumbai)

Tip: relax that requirement to get these options.
============================================================

You: Find an available car in Goa with sunroof

[1/4] understand_query ...
      category=car | hard=3 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 1 candidates

[3/4] validate_results ...
      valid=0 rejected=1 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 1 candidates

[3/4] validate_results ...
      valid=0 rejected=1 relevant=False

[4/4] rank_and_respond ...

============================================================
No listing meets all your requirements.

Closest options (each misses exactly ONE requirement):
1. Honda City  (Delhi) - Rs 2,200 per day
   Misses: location = Goa (actual: Delhi)
2. Hyundai Creta  (Mumbai) - Rs 2,800 per day
   Misses: location = Goa (actual: Mumbai)
3. Mahindra XUV700  (Mumbai) - Rs 4,200 per day
   Misses: location = Goa (actual: Mumbai)

Tip: relax that requirement to get these options.
Details not given (so not applied): price, capacity
============================================================

You: 

You: Find a hotel in Pune with a swimming pool under 1000

[1/4] understand_query ...
      category=hotel | hard=3 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[4/4] rank_and_respond ...

============================================================
No listing meets all your requirements.
Nothing close either. Try relaxing location, budget or capacity.
============================================================


You: 

You: Find a hotel in Pune with a swimming pool under 1000

[1/4] understand_query ...
      category=hotel | hard=3 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[4/4] rank_and_respond ...

============================================================
No listing meets all your requirements.
Nothing close either. Try relaxing location, budget or capacity.
============================================================

You: Find a venue in Pune for 1000 people

[1/4] understand_query ...
      category=venue | hard=2 | soft=0

[2/4] retrieve_listings (attempt 1) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 2) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[2/4] retrieve_listings (attempt 3) ...
      fetched 0 candidates

[3/4] validate_results ...
      valid=0 rejected=0 relevant=False

[4/4] rank_and_respond ...

============================================================
No listing meets all your requirements.

Closest options (each misses exactly ONE requirement):
1. Conference Center Hinjewadi  (Pune) - Rs 45,000 per day
   Misses: capacity >= 1000 (actual: 150)
2. Lawn Garden Venue  (Pune) - Rs 50,000 per day
   Misses: capacity >= 1000 (actual: 500)
3. Grand Banquet Hall  (Pune) - Rs 80,000 per day
   Misses: capacity >= 1000 (actual: 300)
     Find a venue in Pune for 100 people, preferably with AC and parking      

[1/4] understand_query ...
      category=venue | hard=2 | soft=2

[2/4] retrieve_listings (attempt 1) ...
      fetched 3 candidates

[3/4] validate_results ...
      valid=3 rejected=0 relevant=True

[4/4] rank_and_respond ...

============================================================
Top 3 recommendation(s):

1. Conference Center Hinjewadi  (Pune)
   Rs 45,000 per day | capacity 150 | {"indoor": true, "tags": ["ac", "projector", "wifi", "parking"]}
   Why: Meets: location = Pune, capacity >= 100
2. Grand Banquet Hall  (Pune)
   Rs 80,000 per day | capacity 300 | {"indoor": true, "tags": ["ac", "parking", "stage", "catering"]}
   Why: Meets: location = Pune, capacity >= 100
3. Lawn Garden Venue  (Pune)
   Rs 50,000 per day | capacity 500 | {"indoor": false, "tags": ["parking", "stage", "open air"]}
   Why: Meets: location = Pune, capacity >= 100
Details not given (so not applied): budget
============================================================

You: 